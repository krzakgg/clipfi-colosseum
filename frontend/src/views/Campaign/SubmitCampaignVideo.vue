<script setup>
import { reactive, ref } from 'vue'

const props = defineProps({
  campaignId: { type: Number, required: true },
  creatorId: { type: Number, required: true }
})

const form = reactive({
  video_url: '',
  platform: 'youtube',
  content_type: 'Short'
})
const loading = ref(false)
const successMsg = ref('')
const errorMsg = ref('')

const submitVideo = async () => {
  loading.value = true
  successMsg.value = ''
  errorMsg.value = ''

  try {
    const response = await fetch('http://localhost:8000/api/submissions', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        campaign_id: props.campaignId,
        creator_id: props.creatorId,
        video_url: form.video_url,
        platform: form.platform,
        content_type: form.content_type
      })
    })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Nie udało się wysłać materiału')

    successMsg.value = 'Materiał został wysłany do akceptacji firmy.'
    form.video_url = ''
  } catch (error) {
    errorMsg.value = error.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="submission-box">
    <h3>Wyślij materiał do akceptacji</h3>
    <p class="submission-help">Ta opcja działa po zaakceptowaniu Twojej aplikacji przez firmę.</p>
    <div v-if="successMsg" class="alert alert-success">{{ successMsg }}</div>
    <div v-if="errorMsg" class="alert alert-danger">{{ errorMsg }}</div>

    <form class="apply-form" @submit.prevent="submitVideo">
      <div class="form-group">
        <label>Link do opublikowanego materiału</label>
        <input v-model="form.video_url" type="url" placeholder="https://youtube.com/..." required />
      </div>
      <div class="grid-2">
        <label class="form-group">
          <span>Platforma</span>
          <select v-model="form.platform">
            <option value="youtube">YouTube</option>
            <option value="tiktok">TikTok</option>
            <option value="instagram">Instagram</option>
          </select>
        </label>
        <label class="form-group">
          <span>Typ materiału</span>
          <select v-model="form.content_type">
            <option value="Short">Short / Reel</option>
            <option value="LongVideo">Długie wideo</option>
          </select>
        </label>
      </div>
      <button class="btn-submit" type="submit" :disabled="loading">
        {{ loading ? 'Wysyłanie...' : 'Wyślij materiał' }}
      </button>
    </form>
  </div>
</template>
