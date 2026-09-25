<script setup>
import { ref, reactive, onMounted, watch } from 'vue'
import { uploadImages } from '../../utils/uploadImage'

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
const coverFile = ref(null)
const galleryFiles = ref([])
const coverPreview = ref('')
const galleryPreviews = ref([])

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
  cover_image_url: '',
  gallery_image_urls_str: '',
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
    form.cover_image_url = data.cover_image_url || ''
    form.gallery_image_urls_str = data.gallery_image_urls ? data.gallery_image_urls.join(', ') : ''
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

  try {
    const uploadedCover = coverFile.value ? (await uploadImages([coverFile.value]))[0] : form.cover_image_url
    const uploadedGallery = galleryFiles.value.length ? await uploadImages(galleryFiles.value) : []
    const payload = {
    company_id: parseInt(form.company_id),
    title: form.title,
    description: form.description || null,
    is_private: form.is_private,
    cover_image_url: uploadedCover || null,
    gallery_image_urls: [...form.gallery_image_urls_str.split(',').map(url => url.trim()).filter(Boolean), ...uploadedGallery],
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

    const response = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    if (!response.ok) {
      const data = await response.json().catch(() => ({}))
      const details = Array.isArray(data.detail)
        ? data.detail.map(item => `${item.loc?.at(-1) || 'Pole'}: ${item.msg}`).join('; ')
        : data.detail
      throw new Error(details || 'Błąd podczas edycji kampanii')
    }

    const data = await response.json()
    successMessage.value = `Kampania "${data.title}" została zaktualizowana!`
    coverFile.value = null
    galleryFiles.value = []
    coverPreview.value = ''
    galleryPreviews.value = []
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    loading.value = false
  }
}

const handleCoverSelected = (event) => {
  const file = event.target.files[0]
  if (!file) return
  coverFile.value = file
  coverPreview.value = URL.createObjectURL(file)
}

const handleGallerySelected = (event) => {
  const selectedFiles = Array.from(event.target.files)
  if (selectedFiles.length > 20) {
    errorMessage.value = 'Możesz wybrać maksymalnie 20 obrazów do galerii.'
  } else {
    errorMessage.value = ''
  }
  galleryFiles.value = selectedFiles.slice(0, 20)
  galleryPreviews.value = galleryFiles.value.map(file => URL.createObjectURL(file))
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

          <div class="form-group">
            <label>Obraz tytułowy z komputera</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" @change="handleCoverSelected" />
            <img v-if="coverPreview" class="image-preview" :src="coverPreview" alt="Podgląd nowego obrazu tytułowego" />
            <label>Lub wklej URL</label>
            <input v-model="form.cover_image_url" type="url" placeholder="https://.../cover.jpg" />
          </div>

          <div class="form-group">
            <label>Galeria z komputera</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple @change="handleGallerySelected" />
            <small>Możesz wybrać do 20 obrazów jednocześnie.</small>
            <div v-if="galleryPreviews.length" class="image-preview-grid">
              <img v-for="preview in galleryPreviews" :key="preview" class="image-preview" :src="preview" alt="Podgląd nowego obrazu galerii" />
            </div>
            <label>Lub wklej URL-e po przecinku</label>
            <input v-model="form.gallery_image_urls_str" type="text" placeholder="https://.../1.jpg, https://.../2.jpg" />
          </div>
        </fieldset>

        <fieldset>
          <legend>Budżet</legend>
          <div class="grid-2">
            <div class="form-group">
              <label>Całkowity budżet (PLN)</label>
              <input v-model="form.total_budget" type="number" step="0.01" min="0" max="9999999999.99" required />
            </div>
            <div class="form-group">
              <label>Budżet na twórcę (PLN)</label>
              <input v-model="form.budget_per_creator" type="number" step="0.01" min="0" max="99999999.99" />
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

