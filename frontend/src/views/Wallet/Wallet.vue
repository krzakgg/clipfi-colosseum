<script setup>
import { computed, onMounted, ref } from 'vue'
import { Connection, PublicKey, SystemProgram, Transaction } from '@solana/web3.js'
import bs58 from 'bs58'

const LAMPORTS_PER_SOL = 1_000_000_000
const API_URL = 'http://localhost:8000'

const config = ref(null)
const provider = ref(null)
const publicKey = ref('')
const balance = ref(null)
const treasuryBalance = ref(null)
const amount = ref('')
const destination = ref('')
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
  if (!window.solana?.isPhantom) {
    errorMessage.value = 'Zainstaluj portfel Phantom, aby wykonać transakcję.'
    return
  }
  try {
    const response = await window.solana.connect()
    publicKey.value = response.publicKey.toString()
    destination.value = publicKey.value
    await loadBalance(publicKey.value)
  } catch (error) {
    errorMessage.value = error.message || 'Nie udało się połączyć z portfelem.'
  }
}

const submitDeposit = async () => {
  if (!connected.value || !config.value) return
  const sol = Number(amount.value)
  if (!Number.isFinite(sol) || sol <= 0) {
    errorMessage.value = 'Podaj dodatnią kwotę SOL.'
    return
  }
  busy.value = true
  errorMessage.value = ''
  message.value = ''
  try {
    const connection = new Connection(config.value.rpc_url, 'confirmed')
    const transaction = new Transaction().add(SystemProgram.transfer({
      fromPubkey: new PublicKey(publicKey.value),
      toPubkey: new PublicKey(config.value.treasury_address),
      lamports: Math.round(sol * LAMPORTS_PER_SOL)
    }))
    const signature = await window.solana.signAndSendTransaction(transaction)
    await connection.confirmTransaction(signature.signature, 'confirmed')
    message.value = `Wpłata potwierdzona: ${signature.signature}`
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
  const sol = Number(amount.value)
  if (!Number.isFinite(sol) || sol <= 0 || !destination.value) {
    errorMessage.value = 'Podaj dodatnią kwotę SOL i adres docelowy.'
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
      body: JSON.stringify({ wallet_address: publicKey.value, destination: destination.value, lamports })
    })
    const challenge = await challengeResponse.json()
    if (!challengeResponse.ok) throw new Error(challenge.detail || 'Nie udało się utworzyć challenge.')
    const signed = await window.solana.signMessage(
      new TextEncoder().encode(challenge.message),
      'utf8'
    )
    const response = await fetch(`${API_URL}/api/solana/withdraw`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        wallet_address: publicKey.value,
        destination: destination.value,
        lamports,
        nonce: challenge.nonce,
        signature: bs58.encode(signed.signature)
      })
    })
    const result = await response.json()
    if (!response.ok) throw new Error(result.detail || 'Wypłata nie powiodła się.')
    message.value = `Wypłata potwierdzona: ${result.signature}`
    await Promise.all([loadBalance(publicKey.value), loadTreasuryBalance()])
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
      <button v-if="!connected" class="btn-submit" type="button" @click="connectWallet">Połącz Phantom</button>
      <span v-else class="wallet-address">{{ publicKey.slice(0, 6) }}…{{ publicKey.slice(-6) }}</span>
    </div>

    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="message" class="alert alert-success">{{ message }}</div>

    <div class="wallet-stats">
      <div><span>Twoje saldo</span><strong>{{ formatSol(balance) }}</strong></div>
      <div><span>Saldo skarbca</span><strong>{{ formatSol(treasuryBalance) }}</strong></div>
      <div><span>Sieć</span><strong>{{ config?.cluster || '—' }}</strong></div>
    </div>

    <form class="wallet-form" @submit.prevent>
      <label class="form-group">
        <span>Kwota (SOL)</span>
        <input v-model="amount" type="number" min="0.000001" step="0.000001" placeholder="0.10" :disabled="!connected || busy" />
      </label>
      <label class="form-group">
        <span>Adres wypłaty</span>
        <input v-model="destination" type="text" placeholder="Adres Solana Base58" :disabled="!connected || busy" />
      </label>
      <div class="wallet-actions">
        <button class="btn-submit" type="button" :disabled="!connected || busy" @click="submitDeposit">
          {{ busy ? 'Przetwarzanie…' : 'Wpłać SOL' }}
        </button>
        <button class="btn-secondary" type="button" :disabled="!connected || busy" @click="submitWithdrawal">
          Wypłać SOL
        </button>
      </div>
    </form>
    <p class="wallet-note">Wypłata wymaga podpisania jednorazowej wiadomości w portfelu. Klucz skarbca nie jest przechowywany w przeglądarce.</p>
  </section>
</template>
