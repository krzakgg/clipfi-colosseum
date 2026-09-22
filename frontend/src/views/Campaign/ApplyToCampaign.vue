<script setup>
import { ref, reactive } from 'vue'

const props = defineProps({
  campaignId: { type: Number, required: true },
  creatorId: { type: Number, default: 1 } // ID aktualnie zalogowanego twórcy
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
      throw new Error(errData.detail || 'Błąd podczas wysyłania zgłoszenia')
    }

    successMsg.value = 'Zgłoszenie zostało pomyślnie wysłane do marki!'
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
    <h3>Aplikuj do kampanii (ID: {{ campaignId }})</h3>

    <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>
    <div v-if="errorMsg" class="alert alert-danger">{{ errorMsg }}</div>

    <form @submit.prevent="submitApplication" class="apply-form">
      <div class="form-group">
        <label>Proponowany typ materiału</label>
        <select v-model="form.proposed_content_type">
          <option value="Short">Short / Reel / TikTok</option>
          <option value="LongVideo">Długie wideo (YouTube)</option>
        </select>
      </div>

      <div class="form-group">
        <label>Proponowana stawka (PLN)</label>
        <input 
          v-model="form.proposed_rate" 
          type="number" 
          step="0.01" 
          placeholder="np. 500.00 (zostaw puste dla stawki domyślnej)" 
        />
      </div>

      <div class="form-group">
        <label>Twój pomysł / Dlaczego pasujesz do tej marki? (Pitch)</label>
        <textarea 
          v-model="form.pitch" 
          rows="4" 
          placeholder="Opisz krótko swój pomysł na film..."
        ></textarea>
      </div>

      <button type="submit" class="btn-submit" :disabled="loading">
        {{ loading ? 'Wysyłanie...' : 'Wyślij zgłoszenie' }}
      </button>
    </form>
  </div>
</template>

<style scoped>
.apply-box {
  background: #ffffff;
  padding: 1.5rem;
  border-radius: 8px;
  border: 1px solid #e2e8f0;
  max-width: 600px;
  margin: 1rem auto;
  font-family: system-ui, sans-serif;
}
.form-group { display: flex; flex-direction: column; margin-bottom: 1rem; }
.form-group label { font-size: 0.85rem; font-weight: 600; margin-bottom: 0.3rem; }
input, select, textarea { padding: 0.5rem; border: 1px solid #cbd5e0; border-radius: 4px; }
.btn-submit { padding: 0.75rem; background: #38a169; color: white; border: none; border-radius: 6px; font-weight: bold; cursor: pointer; }
.alert { padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; font-size: 0.9rem; }
.alert-success { background: #c6f6d5; color: #22543d; }
.alert-danger { background: #fed7d7; color: #742a2a; }
</style>