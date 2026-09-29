<script setup>
import { ref, reactive } from 'vue'

const props = defineProps({
  campaignId: { type: Number, required: true },
  creatorId: { type: Number, required: true }
})

const loading = ref(false)
const successMsg = ref('')
const errorMsg = ref('')

const form = reactive({
  pitch: '',
  proposed_rate: null,
  proposed_content_type: 'Short'
})

const submitApplication = async () => {
  loading.value = true
  successMsg.value = ''
  errorMsg.value = ''

  const payload = {
    campaign_id: props.campaignId,
    creator_id: props.creatorId,
    pitch: form.pitch || null,
    proposed_rate: form.proposed_rate ? parseFloat(form.proposed_rate) : null,
    proposed_content_type: form.proposed_content_type
  }

  try {
    const res = await fetch('http://localhost:8000/api/applications', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!res.ok) {
      const errData = await res.json()
      throw new Error(errData.detail || 'Application could not be submitted')
    }

    successMsg.value = 'Application submitted successfully!'
    form.pitch = ''
    form.proposed_rate = null
  } catch (err) {
    errorMsg.value = err.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="apply-box">
    <h3>Apply to campaign (ID: {{ campaignId }})</h3>

    <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>
    <div v-if="errorMsg" class="alert alert-danger">{{ errorMsg }}</div>

    <form @submit.prevent="submitApplication" class="apply-form">
      <div class="form-group">
        <label>Proposed content type</label>
        <select v-model="form.proposed_content_type">
          <option value="Short">Short / Reel / TikTok</option>
          <option value="LongVideo">Long-form video (YouTube)</option>
        </select>
      </div>

      <div class="form-group">
        <label>Proposed rate (PLN)</label>
        <input 
          v-model="form.proposed_rate" 
          type="number" 
          step="0.01" 
          placeholder="e.g. 500.00 (leave empty for default rate)"
        />
      </div>

      <div class="form-group">
        <label>Your idea / Why are you a good fit? (Pitch)</label>
        <textarea 
          v-model="form.pitch" 
          rows="4" 
          placeholder="Briefly describe your video idea..."
        ></textarea>
      </div>

      <button type="submit" class="btn-submit" :disabled="loading">
        {{ loading ? 'Submitting...' : 'Submit application' }}
      </button>
    </form>
  </div>
</template>

