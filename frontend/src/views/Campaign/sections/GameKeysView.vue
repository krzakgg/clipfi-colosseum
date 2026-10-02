<script setup>
import { onMounted, ref } from 'vue'

const props = defineProps({ campaignId: { type: Number, required: true }, session: { type: Object, required: true }, isCompanyOwner: { type: Boolean, required: true } })
const keys = ref([])
const keyValue = ref('')
const loading = ref(true)
const saving = ref(false)
const errorMessage = ref('')

const loadKeys = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const url = props.isCompanyOwner
      ? `http://localhost:8000/api/campaigns/${props.campaignId}/game-keys?company_id=${props.session.user.id}`
      : `http://localhost:8000/api/key-requests/creator/${props.session.user.id}`
    const response = await fetch(url)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not load game keys')
    keys.value = props.isCompanyOwner ? data : data.filter(request => request.campaign_id === props.campaignId && request.key_value)
  } catch (error) { errorMessage.value = error.message } finally { loading.value = false }
}

const addKey = async () => {
  if (!keyValue.value.trim()) return
  saving.value = true
  errorMessage.value = ''
  try {
    const response = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}/game-keys`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: props.session.user.id, key_value: keyValue.value.trim() }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not add game key')
    keyValue.value = ''
    await loadKeys()
  } catch (error) { errorMessage.value = error.message } finally { saving.value = false }
}

onMounted(loadKeys)
</script>

<template>
  <section class="campaign-section empty-feature-section">
    <div class="section-heading">
      <div>
        <span class="eyebrow">GAME KEYS</span>
        <h2>Game keys</h2>
        <p>Manage the game keys generated for this campaign.</p>
      </div>
      <span class="section-count">{{ keys.length }} keys</span>
    </div>
    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="isCompanyOwner" class="key-request-form">
      <input v-model="keyValue" type="text" placeholder="Paste a game key" @keyup.enter="addKey" />
      <button class="btn btn-primary" :disabled="saving" @click="addKey">{{ saving ? 'Adding...' : 'Add game key' }}</button>
    </div>
    <div v-if="loading" class="feature-empty-state">Loading game keys...</div>
    <div v-else-if="!keys.length" class="feature-empty-state"><strong>No game keys available</strong><span>Added campaign keys will appear here.</span></div>
    <div v-else class="key-request-list">
      <article v-for="item in keys" :key="item.id" class="key-request-card">
        <strong>{{ isCompanyOwner ? item.key_value : item.key_value }}</strong>
        <span class="status-badge" :class="`status-${item.status || 'assigned'}`">{{ item.status || 'assigned' }}</span>
      </article>
    </div>
  </section>
</template>
