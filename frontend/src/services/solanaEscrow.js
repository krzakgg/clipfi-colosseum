import {
  Connection,
  PublicKey,
  Transaction,
  TransactionInstruction,
} from '@solana/web3.js'

const API_URL = 'http://localhost:8000'

function decodeBase64(value) {
  return Uint8Array.from(atob(value), (character) => character.charCodeAt(0))
}

export async function fundCampaignEscrow({
  campaignId,
  companyWallet,
  rpcUrl,
  walletProvider = window.solana,
}) {
  if (!walletProvider?.publicKey) {
    throw new Error('Połącz portfel firmy przed zasileniem escrow.')
  }
  if (walletProvider.publicKey.toString() !== companyWallet) {
    throw new Error('Połączony portfel nie należy do firmy kampanii.')
  }

  const response = await fetch(
    `${API_URL}/api/solana/campaign/${campaignId}/escrow/funding-instruction`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_wallet: companyWallet }),
    },
  )
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail || 'Nie udało się przygotować escrow.')

  const instruction = new TransactionInstruction({
    programId: new PublicKey(payload.instruction.program_id),
    data: decodeBase64(payload.instruction.data),
    keys: payload.instruction.accounts.map((account) => ({
      pubkey: new PublicKey(account.pubkey),
      isSigner: account.is_signer,
      isWritable: account.is_writable,
    })),
  })
  const connection = new Connection(rpcUrl, 'confirmed')
  const transaction = new Transaction().add(instruction)
  transaction.feePayer = walletProvider.publicKey
  transaction.recentBlockhash = (await connection.getLatestBlockhash('confirmed')).blockhash
  const signature = await walletProvider.sendTransaction(transaction, connection)
  await connection.confirmTransaction(signature, 'confirmed')
  return { ...payload, signature }
}

async function executeEscrowInstruction({
  endpoint,
  campaignId,
  walletAddress,
  rpcUrl,
  walletProvider,
}) {
  if (!walletProvider?.publicKey || walletProvider.publicKey.toString() !== walletAddress) {
    throw new Error('Połączony portfel nie jest potwierdzonym portfelem uczestnika.')
  }
  const response = await fetch(`${API_URL}/api/solana/campaign/${campaignId}/escrow/${endpoint}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ wallet_address: walletAddress }),
  })
  const payload = await response.json()
  if (!response.ok) throw new Error(payload.detail || 'Nie udało się przygotować transakcji escrow.')
  const instruction = new TransactionInstruction({
    programId: new PublicKey(payload.instruction.program_id),
    data: decodeBase64(payload.instruction.data),
    keys: payload.instruction.accounts.map((account) => ({
      pubkey: new PublicKey(account.pubkey),
      isSigner: account.is_signer,
      isWritable: account.is_writable,
    })),
  })
  const connection = new Connection(rpcUrl, 'confirmed')
  const transaction = new Transaction().add(instruction)
  transaction.feePayer = walletProvider.publicKey
  transaction.recentBlockhash = (await connection.getLatestBlockhash('confirmed')).blockhash
  const signature = await walletProvider.sendTransaction(transaction, connection)
  await connection.confirmTransaction(signature, 'confirmed')
  return { ...payload, signature }
}

export const takeCampaignEscrow = (options) => executeEscrowInstruction({
  ...options,
  endpoint: 'release',
})

export const refundCampaignEscrow = (options) => executeEscrowInstruction({
  ...options,
  endpoint: 'refund-instruction',
})
