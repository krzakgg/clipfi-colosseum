<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useWallet } from '../../../composables/useWallet'
import {
  closeCampaign,
  formatClipUsd,
  formatTimestamp,
  fundCampaignEscrow,
  loadAccountWallet,
  loadEscrow,
  loadPayouts,
  loadSolanaConfig,
  releasePayout,
  rolloverCampaign
} from '../../../services/solanaEscrow'

const props = defineProps({ campaignId: { type: Number, required: true }, campaign: { type: Object, required: true }, session: { type: Object, required: true }, isCompanyOwner: { type: Boolean, required: true } })

const wallet = useWallet()
const walletState = wallet.state

const config = ref(null)
const configError = ref('')
const escrow = ref(null)
const escrowLoading = ref(true)
const escrowError = ref('')
const verifiedWallet = ref('')
const verifiedWalletError = ref('')
const payouts = ref([])
const payoutsLoading = ref(false)
const payoutsError = ref('')
const actionBusy = ref('')
const actionMessage = ref('')
const actionError = ref('')
const fundAmount = ref('')
const fundMinBond = ref('')
const rolloverTarget = ref('')
const releaseBusyEpoch = ref(null)
const nowSeconds = ref(Math.floor(Date.now() / 1000))

const isCreator = computed(() => props.session.account_type === 'creator')
const connected = computed(() => walletState.connected)
const walletMatches = computed(() => Boolean(verifiedWallet.value) && walletState.publicKey === verifiedWallet.value)
const onChain = computed(() => escrow.value?.campaign || null)
const rates = computed(() => {
  const list = Array.isArray(onChain.value?.rate_per_mille) ? onChain.value.rate_per_mille : []
  return ['Short', 'Long', 'Stream', 'Clicks'].map((label, index) => ({ label, value: list[index] ?? 0 }))
})
const toBig = (value) => {
  try { return BigInt(String(value ?? 0).replace(/[^0-9-]/g, '') || '0') } catch { return 0n }
}
const freeBudget = computed(() => {
  if (!onChain.value) return '0'
  return (toBig(onChain.value.funded_total) - toBig(onChain.value.reserved) - toBig(onChain.value.paid_total)).toString()
})
const statusLabel = (status) => {
  if (status === null || status === undefined) return 'Unknown'
  if (typeof status === 'object') return Object.keys(status)[0] || 'Unknown'
  return String(status)
}
const canRelease = (payout) => {
  const status = statusLabel(payout.status).toLowerCase()
  return ['pending', 'approved'].includes(status) && Number(payout.unlock_ts || 0) <= nowSeconds.value
}
const formatBps = (bps) => `${(Number(bps || 0) / 100).toFixed(2)}%`
const explorerUrl = (signature) => {
  const cluster = config.value?.cluster || 'devnet'
  const suffix = cluster === 'mainnet-beta' ? '' : `?cluster=${cluster}`
  return `https://explorer.solana.com/tx/${signature}${suffix}`
}

const loadConfig = async () => {
  configError.value = ''
  try {
    config.value = await loadSolanaConfig()
  } catch (error) {
    config.value = null
    configError.value = error.message || 'The Solana configuration is unavailable.'
  }
}

const loadState = async () => {
  escrowLoading.value = true
  escrowError.value = ''
  try {
    escrow.value = await loadEscrow(props.campaignId)
    nowSeconds.value = Math.floor(Date.now() / 1000)
  } catch (error) {
    escrow.value = null
    escrowError.value = error.message || 'Could not load the escrow state.'
  } finally {
    escrowLoading.value = false
  }
}

const loadVerifiedWallet = async () => {
  verifiedWalletError.value = ''
  try {
    const data = await loadAccountWallet(props.session.account_type, props.session.user.id)
    verifiedWallet.value = data?.wallet_address || ''
  } catch (error) {
    verifiedWallet.value = ''
    verifiedWalletError.value = error.message || 'Could not load the verified wallet.'
  }
}

const loadMyPayouts = async () => {
  if (!isCreator.value || !verifiedWallet.value) return
  payoutsLoading.value = true
  payoutsError.value = ''
  try {
    const data = await loadPayouts(props.campaignId, verifiedWallet.value)
    payouts.value = Array.isArray(data) ? data : []
    nowSeconds.value = Math.floor(Date.now() / 1000)
  } catch (error) {
    payouts.value = []
    payoutsError.value = error.message || 'Could not load your payouts.'
  } finally {
    payoutsLoading.value = false
  }
}

const connectWallet = async () => {
  actionError.value = ''
  try {
    await wallet.connect()
  } catch (error) {
    actionError.value = error.message || 'Could not connect the wallet.'
  }
}

const runOwnerAction = async (name, work) => {
  if (!config.value) {
    actionError.value = configError.value || 'The Solana configuration is unavailable.'
    return
  }
  if (!verifiedWallet.value) {
    actionError.value = 'Link and verify the company wallet on the Wallet page first.'
    return
  }
  if (!walletMatches.value) {
    actionError.value = `Connect the verified company wallet ${wallet.shortAddress(verifiedWallet.value)} to continue.`
    return
  }
  actionBusy.value = name
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await work()
    actionMessage.value = `Transaction confirmed: ${result.signature}`
    await loadState()
  } catch (error) {
    actionError.value = error.message || 'The transaction failed.'
  } finally {
    actionBusy.value = ''
  }
}

const submitFund = () => {
  const amount = Number(fundAmount.value)
  if (!Number.isFinite(amount) || amount <= 0) {
    actionError.value = 'Enter a positive clipUSD amount.'
    return
  }
  return runOwnerAction('fund', async () => {
    const result = await fundCampaignEscrow({ campaignId: props.campaignId, companyWallet: verifiedWallet.value, amount: fundAmount.value, minBond: fundMinBond.value, rpcUrl: config.value.rpc_url })
    fundAmount.value = ''
    return result
  })
}

const submitClose = () => {
  if (!window.confirm('Close this campaign escrow and return the free budget to the company wallet?')) return
  return runOwnerAction('close', () => closeCampaign({ campaignId: props.campaignId, companyWallet: verifiedWallet.value, rpcUrl: config.value.rpc_url }))
}

const submitRollover = () => {
  const target = Number(rolloverTarget.value)
  if (!Number.isInteger(target) || target <= 0 || target === props.campaignId) {
    actionError.value = 'Enter a different campaign ID to roll the budget into.'
    return
  }
  return runOwnerAction('rollover', () => rolloverCampaign({ campaignId: props.campaignId, companyWallet: verifiedWallet.value, targetCampaignId: target, rpcUrl: config.value.rpc_url }))
}

const submitRelease = async (payout) => {
  if (!walletMatches.value) {
    actionError.value = `Connect the verified wallet ${wallet.shortAddress(verifiedWallet.value)} to sign the release.`
    return
  }
  releaseBusyEpoch.value = payout.epoch
  actionError.value = ''
  actionMessage.value = ''
  try {
    const result = await releasePayout(props.campaignId, verifiedWallet.value, payout.epoch)
    actionMessage.value = `Payout released: ${result.signature}`
    await Promise.all([loadMyPayouts(), loadState()])
  } catch (error) {
    actionError.value = error.message || 'The release failed.'
  } finally {
    releaseBusyEpoch.value = null
  }
}

const refreshAll = async () => {
  await Promise.all([loadConfig(), loadState(), loadVerifiedWallet()])
  await loadMyPayouts()
}

onMounted(refreshAll)
watch(() => props.campaignId, refreshAll)
</script>

<template>
  <section class="campaign-section empty-feature-section escrow-section">
    <div class="section-heading">
      <div>
        <span class="eyebrow">ON-CHAIN ESCROW</span>
        <h2>Escrow</h2>
        <p>Campaign budget locked in the clipfi_escrow program and paid out in clipUSD.</p>
      </div>
      <div class="escrow-heading-actions">
        <span v-if="config" class="section-count">{{ config.cluster }}</span>
        <button class="btn-secondary" type="button" :disabled="escrowLoading" @click="refreshAll">{{ escrowLoading ? 'Refreshing...' : 'Refresh' }}</button>
      </div>
    </div>

    <div v-if="configError" class="alert alert-danger">{{ configError }}</div>
    <div v-if="escrowError" class="alert alert-danger">{{ escrowError }}</div>
    <div v-if="actionError" class="alert alert-danger">{{ actionError }}</div>
    <div v-if="actionMessage" class="alert alert-success escrow-signature">
      <span>{{ actionMessage }}</span>
      <a v-if="actionMessage.includes(': ')" class="details-link" :href="explorerUrl(actionMessage.split(': ').pop())" target="_blank" rel="noopener">View in explorer</a>
    </div>

    <div v-if="escrowLoading" class="feature-empty-state">Loading escrow state...</div>
    <div v-else-if="!escrow || !escrow.exists" class="feature-empty-state">
      <strong>Not funded yet</strong>
      <span>{{ isCompanyOwner ? 'Fund the escrow below to open this campaign on-chain.' : 'The company has not funded this campaign on-chain yet.' }}</span>
    </div>
    <div v-else class="escrow-grid">
      <article class="info-card escrow-card">
        <h2>Budget</h2>
        <dl>
          <div><dt>Funded</dt><dd>{{ formatClipUsd(onChain.funded_total) }} clipUSD</dd></div>
          <div><dt>Reserved</dt><dd>{{ formatClipUsd(onChain.reserved) }} clipUSD</dd></div>
          <div><dt>Paid</dt><dd>{{ formatClipUsd(onChain.paid_total) }} clipUSD</dd></div>
          <div><dt>Free budget</dt><dd>{{ formatClipUsd(freeBudget) }} clipUSD</dd></div>
          <div><dt>Per-creator cap</dt><dd>{{ formatClipUsd(onChain.max_per_creator) }} clipUSD</dd></div>
          <div><dt>Min bond</dt><dd>{{ formatClipUsd(onChain.min_bond) }} clipUSD</dd></div>
        </dl>
      </article>
      <article class="info-card escrow-card">
        <h2>Rates and window</h2>
        <dl>
          <div v-for="rate in rates" :key="rate.label"><dt>{{ rate.label }} per 1000</dt><dd>{{ formatClipUsd(rate.value) }} clipUSD</dd></div>
          <div><dt>Window</dt><dd>{{ formatTimestamp(onChain.start_ts) }} - {{ formatTimestamp(onChain.end_ts) }}</dd></div>
          <div><dt>Status</dt><dd><span class="status-badge" :class="`status-${statusLabel(onChain.status).toLowerCase()}`">{{ statusLabel(onChain.status) }}</span></dd></div>
          <div><dt>Standards version</dt><dd>{{ onChain.standards_version ?? '-' }}</dd></div>
        </dl>
        <p class="escrow-addresses">
          <span>Campaign PDA <code>{{ escrow.campaign_pda }}</code></span>
          <span>Vault <code>{{ escrow.vault }}</code></span>
        </p>
      </article>
    </div>

    <template v-if="isCompanyOwner">
      <div class="escrow-owner">
        <div class="escrow-wallet-row">
          <div>
            <strong>Company wallet</strong>
            <span v-if="verifiedWalletError" class="escrow-muted">{{ verifiedWalletError }}</span>
            <span v-else-if="!verifiedWallet" class="escrow-muted">No verified wallet. Link one on the Wallet page first.</span>
            <span v-else class="escrow-muted">Verified: {{ wallet.shortAddress(verifiedWallet) }}</span>
          </div>
          <div class="wallet-header-actions">
            <select v-model="walletState.selectedWalletName" aria-label="Select wallet" :disabled="connected">
              <option v-for="name in wallet.walletNames" :key="name" :value="name">{{ name }}</option>
            </select>
            <button v-if="!connected" class="btn-submit" type="button" :disabled="walletState.connecting" @click="connectWallet">{{ walletState.connecting ? 'Connecting...' : 'Connect wallet' }}</button>
            <span v-else class="wallet-address">{{ wallet.shortAddress(walletState.publicKey) }}</span>
          </div>
        </div>
        <div v-if="connected && verifiedWallet && !walletMatches" class="alert alert-danger">
          The connected wallet {{ wallet.shortAddress(walletState.publicKey) }} is not the verified company wallet {{ wallet.shortAddress(verifiedWallet) }}. Switch accounts in the wallet extension and reconnect.
        </div>

        <form class="wallet-form escrow-form" @submit.prevent="submitFund">
          <h3>Fund escrow</h3>
          <label class="form-group">
            <span>Amount (clipUSD)</span>
            <input v-model="fundAmount" type="number" min="0.000001" step="0.000001" placeholder="12.50" :disabled="Boolean(actionBusy)" />
          </label>
          <label class="form-group">
            <span>Min creator bond (clipUSD, optional)</span>
            <input v-model="fundMinBond" type="number" min="0" step="0.000001" placeholder="0" :disabled="Boolean(actionBusy)" />
          </label>
          <div class="wallet-actions">
            <button class="btn-submit" type="submit" :disabled="Boolean(actionBusy) || !connected">{{ actionBusy === 'fund' ? 'Funding...' : 'Fund escrow' }}</button>
          </div>
        </form>

        <form class="wallet-form escrow-form" @submit.prevent="submitRollover">
          <h3>Close or roll over</h3>
          <label class="form-group">
            <span>Target campaign ID for rollover</span>
            <input v-model="rolloverTarget" type="number" min="1" step="1" placeholder="Campaign ID" :disabled="Boolean(actionBusy)" />
          </label>
          <div class="wallet-actions">
            <button class="btn-secondary" type="submit" :disabled="Boolean(actionBusy) || !connected || !escrow?.exists">{{ actionBusy === 'rollover' ? 'Rolling over...' : 'Roll over budget' }}</button>
            <button class="btn-secondary escrow-danger" type="button" :disabled="Boolean(actionBusy) || !connected || !escrow?.exists" @click="submitClose">{{ actionBusy === 'close' ? 'Closing...' : 'Close campaign' }}</button>
          </div>
        </form>
      </div>
    </template>

    <template v-if="isCreator">
      <div class="escrow-payouts">
        <div class="section-heading">
          <div>
            <h2>My payouts</h2>
            <p v-if="verifiedWallet">Payouts for {{ wallet.shortAddress(verifiedWallet) }}</p>
            <p v-else>Link and verify your wallet on the Wallet page to see payouts.</p>
          </div>
          <div class="wallet-header-actions">
            <span class="section-count">{{ payouts.length }} epochs</span>
            <button v-if="!connected" class="btn-submit" type="button" :disabled="walletState.connecting" @click="connectWallet">{{ walletState.connecting ? 'Connecting...' : 'Connect wallet' }}</button>
            <span v-else class="wallet-address">{{ wallet.shortAddress(walletState.publicKey) }}</span>
          </div>
        </div>
        <div v-if="connected && verifiedWallet && !walletMatches" class="alert alert-danger">
          The connected wallet {{ wallet.shortAddress(walletState.publicKey) }} is not your verified wallet {{ wallet.shortAddress(verifiedWallet) }}. Releases must be signed by the verified wallet.
        </div>
        <p v-if="!connected && payouts.length" class="escrow-muted">Releasing a payout signs a message with your wallet; connect it first.</p>
        <div v-if="payoutsError" class="alert alert-danger">{{ payoutsError }}</div>
        <div v-if="payoutsLoading" class="feature-empty-state">Loading payouts...</div>
        <div v-else-if="!payouts.length" class="feature-empty-state"><strong>No payouts yet</strong><span>Settled epochs for this campaign will appear here.</span></div>
        <div v-else class="creator-table payout-table">
          <div class="creator-table-head payout-row"><span>Epoch</span><span>Amount</span><span>Bonus</span><span>Restake</span><span>Unlocks</span><span>Status</span><span></span></div>
          <div v-for="payout in payouts" :key="payout.epoch" class="creator-table-row payout-row">
            <span class="creator-table-value">#{{ payout.epoch }}</span>
            <span class="creator-table-value">{{ formatClipUsd(payout.amount) }} clipUSD</span>
            <span class="creator-table-value">{{ formatBps(payout.bonus_bps) }}</span>
            <span class="creator-table-value">{{ formatBps(payout.restake_bps) }}</span>
            <span class="creator-table-value">{{ formatTimestamp(payout.unlock_ts) }}</span>
            <span><span class="status-badge" :class="`status-${statusLabel(payout.status).toLowerCase()}`">{{ statusLabel(payout.status) }}</span></span>
            <span><button class="btn-submit payout-release" type="button" :disabled="!canRelease(payout) || releaseBusyEpoch !== null" @click="submitRelease(payout)">{{ releaseBusyEpoch === payout.epoch ? 'Releasing...' : 'Release' }}</button></span>
          </div>
        </div>
      </div>
    </template>
  </section>
</template>
