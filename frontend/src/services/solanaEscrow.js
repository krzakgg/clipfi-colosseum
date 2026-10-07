import bs58 from 'bs58'
import { useWallet } from '../composables/useWallet'

const API_URL = 'http://localhost:8000'
const CLIPUSD_DECIMALS = 6

const parseError = (payload, fallback) => {
  if (!payload) return fallback
  if (Array.isArray(payload.detail)) return payload.detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
  return payload.detail || fallback
}

const request = async (path, options = {}) => {
  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: { 'Content-Type': 'application/json', ...(options.headers || {}) }
  })
  let payload = null
  try { payload = await response.json() } catch { payload = null }
  if (!response.ok) {
    const error = new Error(parseError(payload, `Request failed (${response.status})`))
    error.status = response.status
    throw error
  }
  return payload
}

const post = (path, body) => request(path, { method: 'POST', body: JSON.stringify(body) })

export const loadSolanaConfig = () => request('/api/solana/config')

export const loadAccountWallet = (accountType, accountId) => request(`/api/solana/account/${accountType}/${accountId}`)

export const formatClipUsd = (value) => {
  if (value === null || value === undefined || value === '') return '0.000000'
  const digits = String(value).replace(/[^0-9-]/g, '')
  if (!digits || digits === '-') return '0.000000'
  const negative = digits.startsWith('-')
  const raw = BigInt(negative ? digits.slice(1) : digits)
  const base = 10n ** BigInt(CLIPUSD_DECIMALS)
  const whole = (raw / base).toString()
  const fraction = (raw % base).toString().padStart(CLIPUSD_DECIMALS, '0')
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ',')
  return `${negative ? '-' : ''}${grouped}.${fraction}`
}

export const toBaseUnits = (value) => {
  const text = String(value ?? '').trim()
  if (!/^\d+(\.\d{0,6})?$/.test(text)) throw new Error('Enter a non-negative amount with at most 6 decimals.')
  const [whole, fraction = ''] = text.split('.')
  return (BigInt(whole) * 10n ** 6n + BigInt(fraction.padEnd(6, '0'))).toString()
}

export const formatTimestamp = (seconds) => {
  const value = Number(seconds)
  if (!Number.isFinite(value) || value <= 0) return 'Not set'
  return new Date(value * 1000).toLocaleString('en-US')
}

const requireWallet = (expected) => {
  const wallet = useWallet()
  if (!wallet.state.connected || !wallet.state.publicKey) throw new Error('Connect a wallet first.')
  if (expected && wallet.state.publicKey !== expected) {
    throw new Error(`The connected wallet ${wallet.shortAddress(wallet.state.publicKey)} is not the verified wallet ${wallet.shortAddress(expected)}.`)
  }
  return wallet
}

const submit = async (wallet, payload, rpcUrl) => {
  const signature = await wallet.sendInstructions(payload.instructions, rpcUrl)
  return { ...payload, signature }
}

export async function fundCampaignEscrow({ campaignId, companyWallet, amount, minBond, rpcUrl }) {
  const wallet = requireWallet(companyWallet)
  const body = { company_wallet: companyWallet, amount: String(amount) }
  if (minBond !== undefined && minBond !== null && String(minBond).trim() !== '') body.min_bond = String(minBond)
  const payload = await post(`/api/solana/campaign/${campaignId}/escrow/funding-instruction`, body)
  return submit(wallet, payload, rpcUrl)
}

export const loadEscrow = (campaignId) => request(`/api/solana/campaign/${campaignId}/escrow`)

export const loadPayouts = (campaignId, walletAddress) => request(`/api/solana/campaign/${campaignId}/payouts/${walletAddress}`)

export async function releasePayout(campaignId, walletAddress, epoch) {
  const wallet = requireWallet(walletAddress)
  const message = `WAGGI release\ncampaign_id: ${campaignId}\nepoch: ${epoch}\nwallet_address: ${walletAddress}`
  const signed = await wallet.signMessage(new TextEncoder().encode(message))
  return post(`/api/solana/campaign/${campaignId}/escrow/release`, { wallet_address: walletAddress, epoch, signature: bs58.encode(signed) })
}

export async function flagPayout({ campaignId, companyWallet, walletAddress, epoch, reason, rpcUrl }) {
  const wallet = requireWallet(companyWallet)
  const payload = await post(`/api/solana/campaign/${campaignId}/escrow/flag`, { company_wallet: companyWallet, wallet_address: walletAddress, epoch, reason })
  return submit(wallet, payload, rpcUrl)
}

export async function closeCampaign({ campaignId, companyWallet, rpcUrl }) {
  const wallet = requireWallet(companyWallet)
  const payload = await post(`/api/solana/campaign/${campaignId}/escrow/close`, { company_wallet: companyWallet })
  return submit(wallet, payload, rpcUrl)
}

export async function rolloverCampaign({ campaignId, companyWallet, targetCampaignId, rpcUrl }) {
  const wallet = requireWallet(companyWallet)
  const payload = await post(`/api/solana/campaign/${campaignId}/escrow/rollover`, { company_wallet: companyWallet, target_campaign_id: Number(targetCampaignId) })
  return submit(wallet, payload, rpcUrl)
}

export async function stakeAction({ walletAddress, action, amount, bps, rpcUrl }) {
  const wallet = requireWallet(walletAddress)
  const body = { wallet_address: walletAddress, action }
  if (amount !== undefined && amount !== null && String(amount).trim() !== '') body.amount = String(amount)
  if (bps !== undefined && bps !== null && bps !== '') body.bps = Number(bps)
  const payload = await post('/api/solana/stake/instruction', body)
  return submit(wallet, payload, rpcUrl)
}

export const loadStake = (walletAddress) => request(`/api/solana/stake/${walletAddress}`)
