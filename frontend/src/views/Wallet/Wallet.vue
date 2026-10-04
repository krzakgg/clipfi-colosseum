<script setup>
import { computed, onMounted, ref } from 'vue'
import { Connection, PublicKey, SystemProgram, Transaction } from '@solana/web3.js'
import bs58 from 'bs58'
import {
  PhantomWalletAdapter
} from '@solana/wallet-adapter-phantom'
import { SolflareWalletAdapter } from '@solana/wallet-adapter-solflare'

const LAMPORTS_PER_SOL = 1_000_000_000
const API_URL = 'http://localhost:8000'
const wallets = [
  new PhantomWalletAdapter(),
  new SolflareWalletAdapter(),
  new BackpackWalletAdapter()
]

const config = ref(null)
const provider = ref(null)
const publicKey = ref('')
const balance = ref(null)
const treasuryBalance = ref(null)
const internalBalance = ref('0')
const assignedWallet = ref('')
const sourceWallet = ref('')
const withdrawalDestination = ref('')
const selectedWallet = ref(wallets[0])
const manualDeposit = ref(false)
const manualDepositSignature = ref('')
const depositAmount = ref('')
const withdrawalAmount = ref('')
const busy = ref(false)
const message = ref('')
const errorMessage = ref('')

const connected = computed(() => Boolean(publicKey.value))
const formatSol = (lamports) => lamports === null ? '—' : `${(lamports / LAMPORTS_PER_SOL).toFixed(6)} SOL`

const loadBalance = async (address) => {
  const response = await fetch(`${API_URL}/api/solana/balance/${address}`)
  if (!response.ok) throw new Error('Nie udało się pobrać salda Solany')
  balance.value = (await response.json()).lamports
}

const connectWallet = async () => {
  errorMessage.value = ''
  try {
    await selectedWallet.value.connect()
    publicKey.value = selectedWallet.value.publicKey.toString()
    sourceWallet.value = publicKey.value
    withdrawalDestination.value = assignedWallet.value || publicKey.value
    await saveWallet()
    await loadBalance(publicKey.value)
  } catch (error) {
    errorMessage.value = error.message || 'Nie udało się połączyć z portfelem.'
  }
}

const changeWallet = async () => {
  if (busy.value) return
  if (assignedWallet.value && !window.confirm(
    'Czy na pewno chcesz zmienić domyślny portfel dla tego konta?'
  )) return

  errorMessage.value = ''
  message.value = ''
  try {
    if (selectedWallet.value.connected) await selectedWallet.value.disconnect()
    publicKey.value = ''
    sourceWallet.value = ''
    assignedWallet.value = ''
    await connectWallet()
    message.value = 'Domyślny portfel został zmieniony.'
  } catch (error) {
    errorMessage.value = error.message || 'Nie udało się zmienić portfela.'
  }
}

const account = () => {
  const session = JSON.parse(localStorage.getItem('waggi_session') || 'null')
  return { account_type: session?.account_type, account_id: session?.user?.id }
}

const saveWallet = async () => {
  const messageToSign = `WAGGI wallet verification\naccount_type: ${account().account_type}\naccount_id: ${account().account_id}\nwallet_address: ${publicKey.value}`
  const signed = await selectedWallet.value.signMessage(new TextEncoder().encode(messageToSign))
  const response = await fetch(`${API_URL}/api/solana/wallet`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      ...account(),
      wallet_address: publicKey.value,
      signature: bs58.encode(signed)
    })
  })
  if (!response.ok) throw new Error('Nie udało się przypisać portfela do konta.')
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
    errorMessage.value = 'Podaj dodatnią kwotę SOL.'
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
      if (!credited.ok) throw new Error(creditedData.detail || 'Nie udało się zaksięgować wpłaty.')
      internalBalance.value = String(Number(internalBalance.value) + Number(creditedData.internal_amount))
      message.value = `Wpłata zaksięgowana: +${creditedData.internal_amount} waluty wewnętrznej`
      manualDepositSignature.value = ''
      return
    }
    if (sourceWallet.value !== publicKey.value) {
      throw new Error('Portfel źródłowy musi być aktualnie połączony z Phantom.')
    }
    const connection = new Connection(config.value.rpc_url, 'confirmed')
    const transaction = new Transaction().add(SystemProgram.transfer({
      fromPubkey: new PublicKey(sourceWallet.value),
      toPubkey: new PublicKey(config.value.treasury_address),
      lamports: Math.round(sol * LAMPORTS_PER_SOL)
    }))
    const signature = await selectedWallet.value.sendTransaction(transaction, connection)
    await connection.confirmTransaction(signature.signature, 'confirmed')
    message.value = `Wpłata potwierdzona: ${signature.signature}`
    const identity = account()
    const credited = await fetch(`${API_URL}/api/solana/deposit`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        ...identity,
        wallet_address: sourceWallet.value,
        signature: signature.signature
      })
    })
    const creditedData = await credited.json()
    if (!credited.ok) throw new Error(creditedData.detail || 'Nie udało się zaksięgować wpłaty.')
    internalBalance.value = String(Number(internalBalance.value) + Number(creditedData.internal_amount))
    const depositFee = Number(creditedData.fee_lamports || 0) / LAMPORTS_PER_SOL
    message.value = `Wpłata zaksięgowana: +${creditedData.internal_amount} waluty wewnętrznej (prowizja ${depositFee.toFixed(6)} SOL)`
    await Promise.all([loadBalance(publicKey.value), loadTreasuryBalance()])
  } catch (error) {
    errorMessage.value = error.message || 'Wpłata nie powiodła się.'
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
    errorMessage.value = 'Podaj dodatnią kwotę SOL.'
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
    if (!challengeResponse.ok) throw new Error(challenge.detail || 'Nie udało się utworzyć challenge.')
    message.value = `Prowizja: ${(challenge.fee_lamports / LAMPORTS_PER_SOL).toFixed(6)} SOL`
    const signed = await selectedWallet.value.signMessage(new TextEncoder().encode(challenge.message))
    const response = await fetch(`${API_URL}/api/solana/withdraw`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        wallet_address: publicKey.value,
        ...account(),
        destination_wallet_address: withdrawalDestination.value,
        lamports,
        nonce: challenge.nonce,
        signature: bs58.encode(signed.signature)
      })
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || 'Wypłata nie powiodła się.')
    message.value = `Wypłata potwierdzona: ${result.signature} (prowizja została pobrana)`
    await Promise.all([loadBalance(publicKey.value), loadTreasuryBalance()])
    await loadAccount()
  } catch (error) {
    errorMessage.value = error.message || 'Wypłata nie powiodła się.'
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  try {
    const response = await fetch(`${API_URL}/api/solana/config`)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Skarbiec Solany nie jest skonfigurowany.')
    config.value = data
    await loadAccount()
    await loadTreasuryBalance()
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
        <h1>Wpłaty i wypłaty</h1>
        <p class="wallet-subtitle">Transfery SOL są realizowane przez publiczny Solana System Program.</p>
      </div>
      <div class="wallet-header-actions">
        <select v-model="selectedWallet" aria-label="Wybierz portfel">
          <option v-for="wallet in wallets" :key="wallet.name" :value="wallet">{{ wallet.name }}</option>
        </select>
        <button v-if="!connected" class="btn-submit" type="button" @click="connectWallet">Połącz portfel</button>
        <button v-else class="btn-secondary" type="button" :disabled="busy" @click="changeWallet">Zmień portfel</button>
        <span v-if="connected" class="wallet-address">{{ publicKey.slice(0, 6) }}…{{ publicKey.slice(-6) }}</span>
      </div>
    </div>

    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>

    <div class="wallet-stats">
      <div><span>Twoje saldo</span><strong>{{ formatSol(balance) }}</strong></div>
      <div><span>Saldo waluty wewnętrznej</span><strong>{{ internalBalance }}</strong></div>
      <div><span>Sieć</span><strong>{{ config?.cluster || '—' }}</strong></div>
    </div>

    <form class="wallet-form" @submit.prevent>
      <label class="form-group">
        <span>Tryb wpłaty</span>
        <select v-model="manualDeposit" :disabled="busy">
          <option :value="false">Przez podłączony portfel</option>
          <option :value="true">Ręcznie — wysłałem SOL</option>
        </select>
      </label>
      <label class="form-group">
        <span>Portfel źródłowy wpłaty</span>
        <input v-model="sourceWallet" type="text" spellcheck="false" placeholder="Adres portfela źródłowego" :disabled="busy || (!manualDeposit && connected)" />
      </label>
      <label v-if="manualDeposit" class="form-group">
        <span>Podpis transakcji wpłaty</span>
        <input v-model="manualDepositSignature" type="text" spellcheck="false" placeholder="Signature z Solana Explorer" :disabled="busy" />
      </label>
      <label class="form-group">
        <span>Kwota wpłaty (SOL)</span>
        <input v-model="depositAmount" type="number" min="0.000001" step="0.000001" placeholder="0.10" :disabled="!connected || busy" />
      </label>
      <label class="form-group">
        <span>Portfel docelowy wypłaty</span>
        <input v-model="withdrawalDestination" type="text" spellcheck="false" placeholder="Adres portfela docelowego" :disabled="busy" />
      </label>
      <label class="form-group">
        <span>Kwota wypłaty (SOL)</span>
        <input v-model="withdrawalAmount" type="number" min="0.00000001" step="0.00000001" placeholder="1.00" :disabled="!connected || busy" />
      </label>
      <div class="wallet-actions">
        <button class="btn-submit" type="button" :disabled="(!connected && !manualDeposit) || busy" @click="submitDeposit">
          {{ busy ? 'Przetwarzanie…' : 'Wpłać SOL' }}
        </button>
        <button class="btn-secondary" type="button" :disabled="!connected || busy" @click="submitWithdrawal">
          Wypłać SOL
        </button>
      </div>
    </form>
    <p class="wallet-note">Wypłata wymaga podpisania jednorazowej wiadomości w portfelu. Klucz skarbca nie jest przechowywany w przeglądarce.</p>
    <p v-if="manualDeposit" class="wallet-note">
      Wyślij SOL z wybranego portfela na adres skarbca, a następnie wklej podpis transakcji.
      Kwota zostanie odczytana z potwierdzonej transakcji w sieci Solana.
    </p>
    <p v-if="assignedWallet" class="wallet-note">
      Portfel przypisany do wypłat: {{ assignedWallet.slice(0, 8) }}…{{ assignedWallet.slice(-8) }}.
      Użyj przycisku „Zmień portfel”, aby wybrać inny adres w Phantom.
    </p>
  </section>
</template>
