<script setup>
import { computed, onMounted, ref } from 'vue'
import { Connection, PublicKey, SystemProgram, Transaction } from '@solana/web3.js'
import bs58 from 'bs58'
import { useWallet } from '../../composables/useWallet'
import { formatClipUsd, formatTimestamp, loadStake, stakeAction } from '../../services/solanaEscrow'

const LAMPORTS_PER_SOL = 1_000_000_000
const API_URL = 'http://localhost:8000'
const wallet = useWallet()
const walletState = wallet.state
const walletNames = wallet.walletNames

const config = ref(null)
const balance = ref(null)
const treasuryBalance = ref(null)
const internalBalance = ref('0')
const assignedWallet = ref('')
const sourceWallet = ref('')
const withdrawalDestination = ref('')
const manualDeposit = ref(false)
const manualDepositSignature = ref('')
const depositAmount = ref('')
const withdrawalAmount = ref('')
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

const stake = ref(null)
const stakeLoading = ref(false)
const stakeBusy = ref('')
const stakeMessage = ref('')
const stakeError = ref('')
const stakeAmount = ref('')
const unstakeAmount = ref('')
const autoRestakePercent = ref('')

const connected = computed(() => walletState.connected)
const publicKey = computed(() => walletState.publicKey)
const formatSol = (lamports) => lamports === null ? '-' : `${(lamports / LAMPORTS_PER_SOL).toFixed(6)} SOL`

const account = () => {
  const session = JSON.parse(localStorage.getItem('waggi_session') || 'null')
  return { account_type: session?.account_type, account_id: session?.user?.id }
}
const isCreator = computed(() => account().account_type === 'creator')
const bondWallet = computed(() => assignedWallet.value || publicKey.value)
const nowSeconds = ref(Math.floor(Date.now() / 1000))
const unstakeReady = computed(() => {
  if (!stake.value?.exists) return false
  const pending = Number(stake.value.pending_unstake || 0)
  const unlockAt = Number(stake.value.unstake_at || 0)
  return pending > 0 && unlockAt > 0 && unlockAt <= nowSeconds.value
})
const autoRestakeDisplay = computed(() => stake.value?.exists ? `${(Number(stake.value.auto_restake_bps || 0) / 100).toFixed(2)}%` : '-')

const loadBalance = async (address) => {
  const response = await fetch(`${API_URL}/api/solana/balance/${address}`)
  if (!response.ok) throw new Error('Could not load the Solana balance.')
  balance.value = (await response.json()).lamports
}

const connectWallet = async () => {
  errorMessage.value = ''
  try {
    await wallet.connect()
    sourceWallet.value = publicKey.value
    withdrawalDestination.value = assignedWallet.value || publicKey.value
    await saveWallet()
    await loadBalance(publicKey.value)
    if (isCreator.value) await loadBond()
  } catch (error) {
    errorMessage.value = error.message || 'Could not connect the wallet.'
  }
}

const changeWallet = async () => {
  if (busy.value) return
  if (assignedWallet.value && !window.confirm('Change the default wallet for this account?')) return

  errorMessage.value = ''
  message.value = ''
  try {
    await wallet.disconnect()
    sourceWallet.value = ''
    assignedWallet.value = ''
    await connectWallet()
    message.value = 'The default wallet has been changed.'
  } catch (error) {
    errorMessage.value = error.message || 'Could not change the wallet.'
  }
}

const saveWallet = async () => {
  const messageToSign = `WAGGI wallet verification\naccount_type: ${account().account_type}\naccount_id: ${account().account_id}\nwallet_address: ${publicKey.value}`
  const signed = await wallet.signMessage(new TextEncoder().encode(messageToSign))
  const response = await fetch(`${API_URL}/api/solana/wallet`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...account(),
      wallet_address: publicKey.value,
      signature: bs58.encode(signed)
    })
  })
  if (!response.ok) throw new Error('Could not link the wallet to this account.')
  assignedWallet.value = publicKey.value
}

const loadAccount = async () => {
  const identity = account()
  if (!identity.account_type || !identity.account_id) return
  const response = await fetch(`${API_URL}/api/solana/account/${identity.account_type}/${identity.account_id}`)
  if (!response.ok) return
  const data = await response.json()
  internalBalance.value = data.internal_balance
  assignedWallet.value = data.wallet_address || ''
  if (data.wallet_address) {
    sourceWallet.value = data.wallet_address
    withdrawalDestination.value = data.wallet_address
  }
}

const submitDeposit = async () => {
  if ((!connected.value && !manualDeposit.value) || !config.value) return
  const sol = Number(depositAmount.value)
  if (!Number.isFinite(sol) || sol <= 0) {
    errorMessage.value = 'Enter a positive SOL amount.'
    return
  }
  busy.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    if (manualDeposit.value) {
      const credited = await fetch(`${API_URL}/api/solana/deposit`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...account(),
          wallet_address: sourceWallet.value,
          signature: manualDepositSignature.value.trim()
        })
      })
      const creditedData = await credited.json()
      if (!credited.ok) throw new Error(creditedData.detail || 'Could not credit the deposit.')
      internalBalance.value = String(Number(internalBalance.value) + Number(creditedData.internal_amount))
      message.value = `Deposit credited: +${creditedData.internal_amount} internal currency`
      manualDepositSignature.value = ''
      return
    }
    if (sourceWallet.value !== publicKey.value) {
      throw new Error('The source wallet must be the currently connected wallet.')
    }
    const connection = new Connection(config.value.rpc_url, 'confirmed')
    const transaction = new Transaction().add(SystemProgram.transfer({
      fromPubkey: new PublicKey(sourceWallet.value),
      toPubkey: new PublicKey(config.value.treasury_address),
      lamports: Math.round(sol * LAMPORTS_PER_SOL)
    }))
    const signature = await wallet.sendTransaction(transaction, connection)
    message.value = `Deposit confirmed: ${signature}`
    const identity = account()
    const credited = await fetch(`${API_URL}/api/solana/deposit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...identity,
        wallet_address: sourceWallet.value,
        signature
      })
    })
    const creditedData = await credited.json()
    if (!credited.ok) throw new Error(creditedData.detail || 'Could not credit the deposit.')
    internalBalance.value = String(Number(internalBalance.value) + Number(creditedData.internal_amount))
    const depositFee = Number(creditedData.fee_lamports || 0) / LAMPORTS_PER_SOL
    message.value = `Deposit credited: +${creditedData.internal_amount} internal currency (fee ${depositFee.toFixed(6)} SOL)`
    await Promise.all([loadBalance(publicKey.value), loadTreasuryBalance()])
  } catch (error) {
    errorMessage.value = error.message || 'The deposit failed.'
  } finally {
    busy.value = false
  }
}

const loadTreasuryBalance = async () => {
  if (!config.value?.treasury_address) return
  const response = await fetch(`${API_URL}/api/solana/balance/${config.value.treasury_address}`)
  if (response.ok) treasuryBalance.value = (await response.json()).lamports
}

const submitWithdrawal = async () => {
  if (!connected.value || !config.value) return
  const sol = Number(withdrawalAmount.value)
  if (!Number.isFinite(sol) || sol <= 0) {
    errorMessage.value = 'Enter a positive SOL amount.'
    return
  }
  busy.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    const lamports = Math.round(sol * LAMPORTS_PER_SOL)
    const challengeResponse = await fetch(`${API_URL}/api/solana/withdraw/challenge`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...account(),
        wallet_address: publicKey.value,
        destination_wallet_address: withdrawalDestination.value,
        lamports
      })
    })
    const challenge = await challengeResponse.json()
    if (!challengeResponse.ok) throw new Error(challenge.detail || 'Could not create the withdrawal challenge.')
    message.value = `Fee: ${(challenge.fee_lamports / LAMPORTS_PER_SOL).toFixed(6)} SOL`
    const signed = await wallet.signMessage(new TextEncoder().encode(challenge.message))
    const response = await fetch(`${API_URL}/api/solana/withdraw`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        wallet_address: publicKey.value,
        ...account(),
        destination_wallet_address: withdrawalDestination.value,
        lamports,
        nonce: challenge.nonce,
        signature: bs58.encode(signed)
      })
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || 'The withdrawal failed.')
    message.value = `Withdrawal confirmed: ${result.signature} (the fee has been deducted)`
    await Promise.all([loadBalance(publicKey.value), loadTreasuryBalance()])
    await loadAccount()
  } catch (error) {
    errorMessage.value = error.message || 'The withdrawal failed.'
  } finally {
    busy.value = false
  }
}

const loadBond = async () => {
  if (!isCreator.value || !bondWallet.value) return
  stakeLoading.value = true
  stakeError.value = ''
  try {
    stake.value = await loadStake(bondWallet.value)
    nowSeconds.value = Math.floor(Date.now() / 1000)
    if (stake.value?.exists && autoRestakePercent.value === '') {
      autoRestakePercent.value = (Number(stake.value.auto_restake_bps || 0) / 100).toString()
    }
  } catch (error) {
    stake.value = null
    stakeError.value = error.message || 'Could not load the bond.'
  } finally {
    stakeLoading.value = false
  }
}

const runStakeAction = async (action, extra = {}) => {
  if (!connected.value || !config.value) {
    stakeError.value = 'Connect the wallet first.'
    return
  }
  if (assignedWallet.value && assignedWallet.value !== publicKey.value) {
    stakeError.value = `The connected wallet must be the verified wallet ${wallet.shortAddress(assignedWallet.value)}.`
    return
  }
  stakeBusy.value = action
  stakeError.value = ''
  stakeMessage.value = ''
  try {
    const result = await stakeAction({ walletAddress: publicKey.value, action, rpcUrl: config.value.rpc_url, ...extra })
    stakeMessage.value = `Transaction confirmed: ${result.signature}`
    if (action === 'stake') stakeAmount.value = ''
    if (action === 'request_unstake') unstakeAmount.value = ''
    await loadBond()
  } catch (error) {
    stakeError.value = error.message || 'The bond transaction failed.'
  } finally {
    stakeBusy.value = ''
  }
}

const submitStake = () => {
  const amount = Number(stakeAmount.value)
  if (!Number.isFinite(amount) || amount <= 0) {
    stakeError.value = 'Enter a positive clipUSD amount to stake.'
    return
  }
  return runStakeAction('stake', { amount: stakeAmount.value })
}

const submitUnstake = () => {
  const amount = Number(unstakeAmount.value)
  if (!Number.isFinite(amount) || amount <= 0) {
    stakeError.value = 'Enter a positive clipUSD amount to unstake.'
    return
  }
  return runStakeAction('request_unstake', { amount: unstakeAmount.value })
}

const submitWithdrawStake = () => runStakeAction('withdraw_stake')

const submitAutoRestake = () => {
  const percent = Number(autoRestakePercent.value)
  if (!Number.isFinite(percent) || percent < 0 || percent > 100) {
    stakeError.value = 'Auto-restake must be between 0 and 100 percent.'
    return
  }
  return runStakeAction('set_auto_restake', { bps: Math.round(percent * 100) })
}

onMounted(async () => {
  try {
    const response = await fetch(`${API_URL}/api/solana/config`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'The Solana treasury is not configured.')
    config.value = data
    await loadAccount()
    await loadTreasuryBalance()
    await loadBond()
  } catch (error) {
    errorMessage.value = error.message
  }
})
</script>

<template>
  <section class="wallet-page">
    <div class="wallet-header">
      <div>
        <p class="section-eyebrow">SOLANA / WALLET</p>
        <h1>Deposits and withdrawals</h1>
        <p class="wallet-subtitle">SOL transfers are executed through the public Solana System Program.</p>
      </div>
      <div class="wallet-header-actions">
        <select v-model="walletState.selectedWalletName" aria-label="Select wallet" :disabled="connected || busy">
          <option v-for="name in walletNames" :key="name" :value="name">{{ name }}</option>
        </select>
        <button v-if="!connected" class="btn-submit" type="button" :disabled="walletState.connecting" @click="connectWallet">{{ walletState.connecting ? 'Connecting...' : 'Connect wallet' }}</button>
        <button v-else class="btn-secondary" type="button" :disabled="busy" @click="changeWallet">Change wallet</button>
        <span v-if="connected" class="wallet-address">{{ wallet.shortAddress(publicKey) }}</span>
      </div>
    </div>

    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>

    <div class="wallet-stats">
      <div><span>Your balance</span><strong>{{ formatSol(balance) }}</strong></div>
      <div><span>Internal currency balance</span><strong>{{ internalBalance }}</strong></div>
      <div><span>Network</span><strong>{{ config?.cluster || '-' }}</strong></div>
    </div>

    <form class="wallet-form" @submit.prevent>
      <label class="form-group">
        <span>Deposit mode</span>
        <select v-model="manualDeposit" :disabled="busy">
          <option :value="false">Through the connected wallet</option>
          <option :value="true">Manual - I already sent SOL</option>
        </select>
      </label>
      <label class="form-group">
        <span>Deposit source wallet</span>
        <input v-model="sourceWallet" type="text" spellcheck="false" placeholder="Source wallet address" :disabled="busy || (!manualDeposit && connected)" />
      </label>
      <label v-if="manualDeposit" class="form-group">
        <span>Deposit transaction signature</span>
        <input v-model="manualDepositSignature" type="text" spellcheck="false" placeholder="Signature from Solana Explorer" :disabled="busy" />
      </label>
      <label class="form-group">
        <span>Deposit amount (SOL)</span>
        <input v-model="depositAmount" type="number" min="0.000001" step="0.000001" placeholder="0.10" :disabled="(!connected && !manualDeposit) || busy" />
      </label>
      <label class="form-group">
        <span>Withdrawal destination wallet</span>
        <input v-model="withdrawalDestination" type="text" spellcheck="false" placeholder="Destination wallet address" :disabled="busy" />
      </label>
      <label class="form-group">
        <span>Withdrawal amount (SOL)</span>
        <input v-model="withdrawalAmount" type="number" min="0.00000001" step="0.00000001" placeholder="1.00" :disabled="!connected || busy" />
      </label>
      <div class="wallet-actions">
        <button class="btn-submit" type="button" :disabled="(!connected && !manualDeposit) || busy" @click="submitDeposit">
          {{ busy ? 'Processing...' : 'Deposit SOL' }}
        </button>
        <button class="btn-secondary" type="button" :disabled="!connected || busy" @click="submitWithdrawal">
          Withdraw SOL
        </button>
      </div>
    </form>
    <p class="wallet-note">A withdrawal requires signing a one-time message in your wallet. The treasury key is never stored in the browser.</p>
    <p v-if="manualDeposit" class="wallet-note">
      Send SOL from the selected wallet to the treasury address, then paste the transaction signature.
      The amount is read from the confirmed transaction on the Solana network.
    </p>
    <p v-if="assignedWallet" class="wallet-note">
      Wallet linked for withdrawals: {{ wallet.shortAddress(assignedWallet) }}.
      Use "Change wallet" to pick a different address in your wallet extension.
    </p>

    <section v-if="isCreator" class="bond-card">
      <div class="bond-heading">
        <div>
          <p class="section-eyebrow">CLIPFI / BOND</p>
          <h2>Creator bond</h2>
          <p class="wallet-subtitle">Stake clipUSD as a bond to unlock campaign payouts. Unstaking has a cooldown before withdrawal.</p>
        </div>
        <button class="btn-secondary" type="button" :disabled="stakeLoading || !bondWallet" @click="loadBond">{{ stakeLoading ? 'Refreshing...' : 'Refresh' }}</button>
      </div>

      <div v-if="stakeError" class="alert alert-danger">{{ stakeError }}</div>
      <div v-if="stakeMessage" class="alert alert-success">{{ stakeMessage }}</div>

      <div v-if="!bondWallet" class="feature-empty-state"><strong>No wallet linked</strong><span>Connect a wallet to load your bond.</span></div>
      <template v-else>
        <div class="wallet-stats bond-stats">
          <div><span>Current bond</span><strong>{{ stake?.exists ? `${formatClipUsd(stake.amount)} clipUSD` : 'No bond yet' }}</strong></div>
          <div><span>Pending unstake</span><strong>{{ stake?.exists ? `${formatClipUsd(stake.pending_unstake)} clipUSD` : '-' }}</strong></div>
          <div><span>Unlocks at</span><strong>{{ stake?.exists && Number(stake.pending_unstake || 0) > 0 ? formatTimestamp(stake.unstake_at) : '-' }}</strong></div>
          <div><span>Slashed total</span><strong>{{ stake?.exists ? `${formatClipUsd(stake.slashed_total)} clipUSD` : '-' }}</strong></div>
          <div><span>Auto-restake</span><strong>{{ autoRestakeDisplay }}</strong></div>
          <div><span>Bond wallet</span><strong class="bond-wallet">{{ wallet.shortAddress(bondWallet) }}</strong></div>
        </div>

        <div class="bond-actions">
          <form class="wallet-form bond-form" @submit.prevent="submitStake">
            <label class="form-group">
              <span>Stake (clipUSD)</span>
              <input v-model="stakeAmount" type="number" min="0.000001" step="0.000001" placeholder="10.00" :disabled="!connected || Boolean(stakeBusy)" />
            </label>
            <button class="btn-submit" type="submit" :disabled="!connected || Boolean(stakeBusy)">{{ stakeBusy === 'stake' ? 'Staking...' : 'Stake' }}</button>
          </form>
          <form class="wallet-form bond-form" @submit.prevent="submitUnstake">
            <label class="form-group">
              <span>Request unstake (clipUSD)</span>
              <input v-model="unstakeAmount" type="number" min="0.000001" step="0.000001" placeholder="5.00" :disabled="!connected || Boolean(stakeBusy)" />
            </label>
            <button class="btn-secondary" type="submit" :disabled="!connected || Boolean(stakeBusy)">{{ stakeBusy === 'request_unstake' ? 'Requesting...' : 'Request unstake' }}</button>
          </form>
          <form class="wallet-form bond-form" @submit.prevent="submitWithdrawStake">
            <label class="form-group">
              <span>Withdraw unstaked bond</span>
              <input :value="stake?.exists ? `${formatClipUsd(stake.pending_unstake)} clipUSD` : '-'" type="text" disabled />
            </label>
            <button class="btn-secondary" type="submit" :disabled="!connected || Boolean(stakeBusy) || !unstakeReady">{{ stakeBusy === 'withdraw_stake' ? 'Withdrawing...' : 'Withdraw' }}</button>
          </form>
          <form class="wallet-form bond-form" @submit.prevent="submitAutoRestake">
            <label class="form-group">
              <span>Auto-restake (% of each payout)</span>
              <input v-model="autoRestakePercent" type="number" min="0" max="100" step="0.01" placeholder="25" :disabled="!connected || Boolean(stakeBusy)" />
            </label>
            <button class="btn-secondary" type="submit" :disabled="!connected || Boolean(stakeBusy)">{{ stakeBusy === 'set_auto_restake' ? 'Saving...' : 'Set auto-restake' }}</button>
          </form>
        </div>
        <p v-if="!connected" class="wallet-note">Connect the linked wallet to sign bond transactions.</p>
      </template>
    </section>
  </section>
</template>
