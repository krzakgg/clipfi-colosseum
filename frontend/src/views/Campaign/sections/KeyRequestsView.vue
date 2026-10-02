<script setup>
import { computed, onMounted, ref } from 'vue'

const props = defineProps({
  campaignId: { type: Number, required: true },
  session: { type: Object, required: true },
  isCompanyOwner: { type: Boolean, required: true },
})

const requests = ref([])
const loading = ref(true)
const saving = ref(false)
const errorMessage = ref('')
const requestMessage = ref('')
const creatorRequest = computed(() => requests.value.find(request => request.creator_id === props.session.user.id))

const loadRequests = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const url = props.isCompanyOwner
      ? `http://localhost:8000/api/campaigns/${props.campaignId}/key-requests?company_id=${props.session.user.id}`
      : `http://localhost:8000/api/key-requests/creator/${props.session.user.id}`
    const response = await fetch(url)
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not load key requests')
    requests.value = props.isCompanyOwner ? data : data.filter(request => request.campaign_id === props.campaignId)
  } catch (error) { errorMessage.value = error.message } finally { loading.value = false }
}

const createRequest = async () => {
  saving.value = true
  errorMessage.value = ''
  try {
    const response = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}/key-requests`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ creator_id: props.session.user.id, message: requestMessage.value || null }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not request a game key')
    requestMessage.value = ''
    await loadRequests()
  } catch (error) { errorMessage.value = error.message } finally { saving.value = false }
}

const updateStatus = async (request, status) => {
  saving.value = true
  errorMessage.value = ''
  try {
    const response = await fetch(`http://localhost:8000/api/key-requests/${request.id}/status`, {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ company_id: props.session.user.id, status }),
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Could not update key request')
    await loadRequests()
  } catch (error) { errorMessage.value = error.message } finally { saving.value = false }
}

onMounted(loadRequests)
</script>

<template>
  <section class="campaign-section empty-feature-section">
    <div class="section-heading">
      <div>
        <span class="eyebrow">KEY REQUESTS</span>
        <h2>Key requests</h2>
        <p>Review requests from creators who need a game key for this campaign.</p>
      </div>
      <span class="section-count">{{ requests.length }} requests</span>
    </div>
    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <div v-if="!isCompanyOwner && !creatorRequest" class="key-request-form">
      <textarea v-model="requestMessage" rows="3" placeholder="Add a message for the campaign owner (optional)"></textarea>
      <button class="btn btn-primary" :disabled="saving" @click="createRequest">{{ saving ? 'Sending...' : 'Request a game key' }}</button>
    </div>
    <div v-if="loading" class="feature-empty-state">Loading key requests...</div>
    <div v-else-if="!requests.length" class="feature-empty-state"><strong>No key requests yet</strong><span>Creator requests will appear here.</span></div>
    <div v-else class="key-request-list">
      <article v-for="request in requests" :key="request.id" class="key-request-card">
        <div><strong>Creator #{{ request.creator_id }}</strong><span>{{ request.message || 'No message' }}</span></div>
        <span class="status-badge" :class="`status-${request.status}`">{{ request.status }}</span>
        <div v-if="isCompanyOwner && request.status === 'pending'" class="key-request-actions">
          <button class="btn btn-primary" :disabled="saving" @click="updateStatus(request, 'approved')">Approve and assign key</button>
          <button class="btn btn-reject" :disabled="saving" @click="updateStatus(request, 'rejected')">Reject</button>
        </div>
      </article>
    </div>
  </section>
</template>
