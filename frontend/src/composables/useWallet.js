import { computed, reactive } from 'vue'
import { Connection, PublicKey, Transaction, TransactionInstruction } from '@solana/web3.js'
import { PhantomWalletAdapter } from '@solana/wallet-adapter-phantom'
import { SolflareWalletAdapter } from '@solana/wallet-adapter-solflare'

const adapters = [new PhantomWalletAdapter(), new SolflareWalletAdapter()]

const state = reactive({
  selectedWalletName: adapters[0].name,
  publicKey: '',
  connected: false,
  connecting: false
})

const selectedAdapter = () => adapters.find((adapter) => adapter.name === state.selectedWalletName) || adapters[0]

const syncState = () => {
  const adapter = selectedAdapter()
  state.publicKey = adapter.publicKey ? adapter.publicKey.toString() : ''
  state.connected = Boolean(adapter.connected && adapter.publicKey)
}

for (const adapter of adapters) {
  adapter.on('connect', syncState)
  adapter.on('disconnect', syncState)
}

const connect = async (walletName) => {
  if (walletName) state.selectedWalletName = walletName
  const adapter = selectedAdapter()
  state.connecting = true
  try {
    if (!adapter.connected) await adapter.connect()
    syncState()
    if (!state.publicKey) throw new Error('Wallet connected but no public key was returned.')
    return state.publicKey
  } finally {
    state.connecting = false
  }
}

const disconnect = async () => {
  const adapter = selectedAdapter()
  if (adapter.connected) await adapter.disconnect()
  syncState()
}

const signMessage = async (bytes) => {
  const adapter = selectedAdapter()
  if (!adapter.connected) throw new Error('Connect a wallet first.')
  const payload = bytes instanceof Uint8Array ? bytes : new TextEncoder().encode(String(bytes))
  return adapter.signMessage(payload)
}

const decodeBase64 = (value) => Uint8Array.from(atob(value), (character) => character.charCodeAt(0))

const toInstruction = (item) => new TransactionInstruction({
  programId: new PublicKey(item.program_id),
  data: decodeBase64(item.data || ''),
  keys: (item.accounts || []).map((account) => ({
    pubkey: new PublicKey(account.pubkey),
    isSigner: Boolean(account.is_signer),
    isWritable: Boolean(account.is_writable)
  }))
})

const sendTransaction = async (transaction, connection) => {
  const adapter = selectedAdapter()
  if (!adapter.connected || !adapter.publicKey) throw new Error('Connect a wallet first.')
  const signature = await adapter.sendTransaction(transaction, connection)
  await connection.confirmTransaction(signature, 'confirmed')
  return signature
}

const sendInstructions = async (instructions, rpcUrl) => {
  const adapter = selectedAdapter()
  if (!adapter.connected || !adapter.publicKey) throw new Error('Connect a wallet first.')
  if (!Array.isArray(instructions) || !instructions.length) throw new Error('The backend returned no instructions.')
  if (!rpcUrl) throw new Error('RPC URL is not configured.')
  const connection = new Connection(rpcUrl, 'confirmed')
  const transaction = new Transaction()
  for (const item of instructions) transaction.add(toInstruction(item))
  transaction.feePayer = adapter.publicKey
  const latest = await connection.getLatestBlockhash('confirmed')
  transaction.recentBlockhash = latest.blockhash
  const signature = await adapter.sendTransaction(transaction, connection)
  await connection.confirmTransaction({ signature, blockhash: latest.blockhash, lastValidBlockHeight: latest.lastValidBlockHeight }, 'confirmed')
  return signature
}

const shortAddress = (address) => address ? `${address.slice(0, 6)}...${address.slice(-6)}` : ''

export const walletStore = state

export function useWallet() {
  return {
    adapters,
    state,
    walletNames: adapters.map((adapter) => adapter.name),
    publicKey: computed(() => state.publicKey),
    connected: computed(() => state.connected),
    connecting: computed(() => state.connecting),
    selectedAdapter,
    connect,
    disconnect,
    signMessage,
    sendTransaction,
    sendInstructions,
    shortAddress
  }
}
