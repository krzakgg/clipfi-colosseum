<script setup>
import { ref, reactive, onMounted, watch } from 'vue'

const props = defineProps({
  campaignId: {
    type: Number,
    default: 1
  }
})

const loading = ref(false)
const fetching = ref(false)
const successMessage = ref('')
const errorMessage = ref('')
const companies = ref([])

const fetchCompanies = async () => {
  try {
    const res = await fetch('http://localhost:8000/api/companies')
    if (res.ok) companies.value = await res.json()
  } catch (err) {
    console.error('Błąd pobierania firm:', err)
  }
}

const form = reactive({
  company_id: '',
  title: '',
  description: '',
  is_private: false,
  product_description: '',
  press_kit_url: '',
  brand_guidelines: '',
  total_budget: 0,
  budget_per_creator: 0,
  languages_str: '',
  min_views: 0,
  min_subscribers: 0,
  max_videos_per_creator: 1,
  short_payout: 0,
  long_payout: 0,
  payout_per_views: 0,
  payout_per_click: 0
})

const loadCampaign = async () => {
  if (!props.campaignId) return
  fetching.value = true
  errorMessage.value = ''

  try {
    const res = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}`)
    if (!res.ok) throw new Error('Nie znaleziono kampanii o podanym ID')

    const data = await res.json()

    form.company_id = data.company_id
    form.title = data.title || ''
    form.description = data.description || ''
    form.is_private = data.is_private || false
    form.product_description = data.product_description || ''
    form.press_kit_url = data.press_kit_url || ''
    form.brand_guidelines = data.brand_guidelines || ''
    form.total_budget = data.total_budget
    form.budget_per_creator = data.budget_per_creator || 0
    form.languages_str = data.languages ? data.languages.join(', ') : ''
    form.min_views = data.min_views || 0
    form.min_subscribers = data.min_subscribers || 0
    form.max_videos_per_creator = data.max_videos_per_creator || 1
    
    if (data.payout_by_content_type) {
      form.short_payout = data.payout_by_content_type.Short || 0
      form.long_payout = data.payout_by_content_type.LongVideo || 0
    }
    form.payout_per_views = data.payout_per_views || 0
    form.payout_per_click = data.payout_per_click || 0
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    fetching.value = false
  }
}

watch(() => props.campaignId, loadCampaign)

onMounted(async () => {
  await fetchCompanies()
  await loadCampaign()
})

const handleUpdate = async () => {
  loading.value = true
  successMessage.value = ''
  errorMessage.value = ''

  const payload = {
    company_id: parseInt(form.company_id),
    title: form.title,
    description: form.description || null,
    is_private: form.is_private,
    product_description: form.product_description || null,
    press_kit_url: form.press_kit_url || null,
    brand_guidelines: form.brand_guidelines || null,
    total_budget: parseFloat(form.total_budget),
    budget_per_creator: form.budget_per_creator ? parseFloat(form.budget_per_creator) : null,
    languages: form.languages_str.split(',').map(l => l.trim().toUpperCase()).filter(Boolean),
    min_views: parseInt(form.min_views) || 0,
    min_subscribers: parseInt(form.min_subscribers) || 0,
    max_videos_per_creator: form.max_videos_per_creator ? parseInt(form.max_videos_per_creator) : null,
    payout_by_content_type: {
      Short: form.short_payout ? parseFloat(form.short_payout) : 0,
      LongVideo: form.long_payout ? parseFloat(form.long_payout) : 0
    },
    payout_per_views: form.payout_per_views ? parseFloat(form.payout_per_views) : null,
    payout_per_click: form.payout_per_click ? parseFloat(form.payout_per_click) : null
  }

  try {
    const response = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!response.ok) throw new Error('Błąd podczas edycji kampanii')

    const data = await response.json()
    successMessage.value = `Kampania "${data.title}" została zaktualizowana!`
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="edit-container">
    <h2>Edycja kampanii (ID: {{ campaignId }})</h2>

    <div v-if="fetching">Wczytywanie danych kampanii...</div>

    <template v-else>
      <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>
      <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

      <form @submit.prevent="handleUpdate" class="campaign-form">
        <fieldset>
          <legend>Podstawowe dane</legend>
          
          <div class="form-group">
            <label>Przypisana firma *</label>
            <select v-model="form.company_id" required>
              <option value="" disabled>-- Wybierz firmę --</option>
              <option v-for="company in companies" :key="company.id" :value="company.id">
                {{ company.name }} (ID: {{ company.id }})
              </option>
            </select>
          </div>

          <div class="form-group">
            <label>Tytuł kampanii</label>
            <input v-model="form.title" type="text" required />
          </div>
          <div class="form-group">
            <label>Opis kampanii</label>
            <textarea v-model="form.description" rows="3"></textarea>
          </div>
        </fieldset>

        <fieldset>
          <legend>Budżet</legend>
          <div class="grid-2">
            <div class="form-group">
              <label>Całkowity budżet (PLN)</label>
              <input v-model="form.total_budget" type="number" step="0.01" required />
            </div>
            <div class="form-group">
              <label>Budżet na twórcę (PLN)</label>
              <input v-model="form.budget_per_creator" type="number" step="0.01" />
            </div>
          </div>
        </fieldset>

        <button type="submit" class="btn-submit" :disabled="loading">
          {{ loading ? 'Zapisywanie...' : 'Zapisz zmiany' }}
        </button>
      </form>
    </template>
  </div>
</template>

<style scoped>
.edit-container {
  max-width: 800px;
  margin: 2rem auto;
  padding: 1.5rem;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0,0,0,0.05);
  font-family: system-ui, sans-serif;
}
fieldset { border: 1px solid #e2e8f0; padding: 1rem; margin-bottom: 1rem; border-radius: 6px; }
.form-group { display: flex; flex-direction: column; margin-bottom: 0.8rem; }
.form-group label { font-size: 0.85rem; font-weight: 600; margin-bottom: 0.2rem; }
input, textarea { padding: 0.5rem; border: 1px solid #cbd5e0; border-radius: 4px; }
.grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1rem; }
.btn-submit { width: 100%; padding: 0.75rem; background: #2b6cb0; color: white; border: none; border-radius: 6px; cursor: pointer; font-weight: bold; }
.alert { padding: 0.75rem; border-radius: 6px; margin-bottom: 1rem; }
.alert-success { background: #c6f6d5; color: #22543d; }
.alert-danger { background: #fed7d7; color: #742a2a; }
</style>