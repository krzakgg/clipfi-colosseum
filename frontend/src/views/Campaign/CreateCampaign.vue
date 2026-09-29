<script setup>
import { ref, reactive, onMounted } from 'vue'
import { uploadImages } from '../../utils/uploadImage'

const emit = defineEmits(['campaign-created'])

const loading = ref(false)
const successMessage = ref('')
const errorMessage = ref('')
const companies = ref([])
const coverFile = ref(null)
const galleryFiles = ref([])
const coverPreview = ref('')
const galleryPreviews = ref([])

const parseJsonField = (value, label) => {
  if (!value.trim()) return null
  try {
    const parsed = JSON.parse(value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    return parsed
  } catch {
    throw new Error(`${label} musi zawierać poprawny obiekt JSON.`)
  }
}

// Pobieranie listy firm z backendu
const fetchCompanies = async () => {
  try {
    const res = await fetch('http://localhost:8000/api/companies')
    if (res.ok) {
      companies.value = await res.json()
    } else {
      console.error('Nie udało się pobrać listy firm.')
    }
  } catch (err) {
    console.error('Błąd połączenia z serwerem:', err)
  }
}

onMounted(fetchCompanies)

// Reaktywny stan formularza
const form = reactive({
  company_id: '',
  title: '',
  description: '',
  status: 'DRAFT',
  is_private: false,
  cover_image_url: '',
  gallery_image_urls_str: '',

  // Opis i materiały
  product_description: '',
  press_kit_url: '',
  brand_guidelines: '',

  // Budżet
  total_budget: null,
  budget_per_creator: null,
  budget_per_time_unit: null,
  budget_per_language_str: '',

  // Wymagania i zasady
  languages_str: 'PL, EN',
  min_views: 0,
  min_subscribers: 0,
  max_videos_per_creator: 1,
  max_submissions_per_day: null,
  platform_requirements_str: '',
  start_date: '',
  end_date: '',
  rollover_remaining_budget: false,

  // Linki kampanii
  social_media_links_str: '',

  // Stawki i rozliczenie
  short_payout: null,
  long_payout: null,
  payout_per_views: null,
  views_unit_step: 1000,
  payout_per_click: null
})

const handleSubmit = async () => {
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
      status: form.status,
      is_private: form.is_private,
      cover_image_url: uploadedCover || null,
      gallery_image_urls: [...form.gallery_image_urls_str.split(',').map(url => url.trim()).filter(Boolean), ...uploadedGallery],

      product_description: form.product_description || null,
      press_kit_url: form.press_kit_url || null,
      brand_guidelines: form.brand_guidelines || null,

      total_budget: parseFloat(form.total_budget),
      budget_per_creator: form.budget_per_creator ? parseFloat(form.budget_per_creator) : null,
      budget_per_time_unit: form.budget_per_time_unit ? parseFloat(form.budget_per_time_unit) : null,
      budget_per_language: parseJsonField(form.budget_per_language_str, 'Budżet według języka'),

      languages: form.languages_str.split(',').map(l => l.trim().toUpperCase()).filter(Boolean),
      min_views: parseInt(form.min_views) || 0,
      min_subscribers: parseInt(form.min_subscribers) || 0,
      max_videos_per_creator: form.max_videos_per_creator ? parseInt(form.max_videos_per_creator) : null,
      max_submissions_per_day: form.max_submissions_per_day ? parseInt(form.max_submissions_per_day) : null,
      platform_requirements: parseJsonField(form.platform_requirements_str, 'Wymagania platform'),
      start_date: form.start_date || null,
      end_date: form.end_date || null,
      rollover_remaining_budget: form.rollover_remaining_budget,
      social_media_links: parseJsonField(form.social_media_links_str, 'Linki social media'),

      payout_by_content_type: {
        Short: form.short_payout ? parseFloat(form.short_payout) : 0,
        LongVideo: form.long_payout ? parseFloat(form.long_payout) : 0
      },
      payout_per_views: form.payout_per_views ? parseFloat(form.payout_per_views) : null,
      views_unit_step: parseInt(form.views_unit_step) || 1000,
      payout_per_click: form.payout_per_click ? parseFloat(form.payout_per_click) : null
    }

    const response = await fetch('http://localhost:8000/api/campaigns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    const data = await response.json()

    if (!response.ok) {
      const details = Array.isArray(data.detail)
        ? data.detail.map(item => `${item.loc?.at(-1) || 'Pole'}: ${item.msg}`).join('; ')
        : data.detail
      throw new Error(details || 'Błąd podczas tworzenia kampanii')
    }

    successMessage.value = `Kampania "${data.title}" została pomyślnie utworzona!`
    
    // Reset stanu formularza
    Object.assign(form, {
      company_id: '',
      title: '',
      description: '',
      status: 'DRAFT',
      is_private: false,
      cover_image_url: '',
      gallery_image_urls_str: '',
      product_description: '',
      press_kit_url: '',
      brand_guidelines: '',
      total_budget: null,
      budget_per_creator: null,
      budget_per_time_unit: null,
      budget_per_language_str: '',
      languages_str: 'PL, EN',
      min_views: 0,
      min_subscribers: 0,
      max_videos_per_creator: 1,
      max_submissions_per_day: null,
      platform_requirements_str: '',
      start_date: '',
      end_date: '',
      rollover_remaining_budget: false,
      social_media_links_str: '',
      short_payout: null,
      long_payout: null,
      payout_per_views: null,
      views_unit_step: 1000,
      payout_per_click: null
    })
    coverFile.value = null
    galleryFiles.value = []
    coverPreview.value = ''
    galleryPreviews.value = []

    // Emitowanie zdarzenia do rodzica (np. App.vue)
    emit('campaign-created', data)
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
  <div class="campaign-container">
    <h2>Stwórz nową kampanię</h2>

    <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

    <form @submit.prevent="handleSubmit" class="campaign-form">
      
      <!-- Sekcja 1: Podstawowe informacje -->
      <fieldset>
        <legend>1. Podstawowe informacje</legend>
        
        <div class="form-group">
          <label>Wybierz firmę *</label>
          <select v-model="form.company_id" required>
            <option value="" disabled>-- Wybierz firmę z listy --</option>
            <option v-for="company in companies" :key="company.id" :value="company.id">
              {{ company.name }} (ID: {{ company.id }})
            </option>
          </select>
        </div>

        <div class="form-group">
          <label>Tytuł kampanii *</label>
          <input v-model="form.title" type="text" placeholder="np. Letnia promocja aplikacji" required />
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Status kampanii</label>
            <select v-model="form.status">
              <option value="DRAFT">Szkic</option>
              <option value="ACTIVE">Aktywna</option>
              <option value="PAUSED">Wstrzymana</option>
              <option value="COMPLETED">Zakończona</option>
              <option value="CANCELLED">Anulowana</option>
            </select>
          </div>
          <div class="form-group checkbox-group">
            <label>
              <input type="checkbox" v-model="form.is_private" />
              Kampania prywatna
            </label>
          </div>
        </div>

        <div class="form-group">
          <label>Opis ogólny</label>
          <textarea v-model="form.description" rows="3" placeholder="Krótki opis celu kampanii..."></textarea>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Obraz tytułowy z komputera</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" @change="handleCoverSelected" />
            <img v-if="coverPreview" class="image-preview" :src="coverPreview" alt="Podgląd obrazu tytułowego" />
            <label>Lub wklej URL</label>
            <input v-model="form.cover_image_url" type="url" placeholder="https://.../cover.jpg" />
          </div>

          <div class="form-group">
            <label>Galeria z komputera</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple @change="handleGallerySelected" />
            <small>Możesz wybrać do 20 obrazów jednocześnie.</small>
            <div v-if="galleryPreviews.length" class="image-preview-grid">
              <img v-for="preview in galleryPreviews" :key="preview" class="image-preview" :src="preview" alt="Podgląd obrazu galerii" />
            </div>
            <label>Lub wklej URL-e po przecinku</label>
            <input v-model="form.gallery_image_urls_str" type="text" placeholder="https://.../1.jpg, https://.../2.jpg" />
          </div>
        </div>
      </fieldset>

      <!-- Sekcja 2: Materiały i Opis Produktu -->
      <fieldset>
        <legend>2. Materiały dla twórców</legend>

        <div class="form-group">
          <label>Szczegółowy opis produktu</label>
          <textarea v-model="form.product_description" rows="3" placeholder="Opisz kluczowe funkcje produktu..."></textarea>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Link do Press Kit (URL)</label>
            <input v-model="form.press_kit_url" type="url" placeholder="https://..." />
          </div>

          <div class="form-group">
            <label>Wytyczne marki (Brand Guidelines)</label>
            <input v-model="form.brand_guidelines" type="text" placeholder="np. Zasady użycia logo, kolory..." />
          </div>
        </div>
      </fieldset>

      <!-- Sekcja 3: Budżet i Wymagania -->
      <fieldset>
        <legend>3. Budżet i Wymagania</legend>

        <div class="grid-2">
          <div class="form-group">
            <label>Całkowity budżet (PLN) *</label>
            <input v-model="form.total_budget" type="number" step="0.01" min="0" max="9999999999.99" placeholder="10000.00" required />
          </div>

          <div class="form-group">
            <label>Budżet na 1 twórcę (PLN)</label>
            <input v-model="form.budget_per_creator" type="number" step="0.01" min="0" max="99999999.99" placeholder="1500.00" />
          </div>
          <div class="form-group">
            <label>Budżet na jednostkę czasu (PLN)</label>
            <input v-model="form.budget_per_time_unit" type="number" step="0.01" min="0" max="99999999.99" placeholder="500.00" />
          </div>
        </div>

        <div class="form-group">
          <label>Budżet według języka (JSON)</label>
          <textarea v-model="form.budget_per_language_str" rows="2" placeholder='{"PL": 1000, "EN": 1200}'></textarea>
        </div>

        <div class="grid-3">
          <div class="form-group">
            <label>Języki (oddzielone przecinkami)</label>
            <input v-model="form.languages_str" type="text" placeholder="PL, EN" />
          </div>

          <div class="form-group">
            <label>Min. wyświetleń</label>
            <input v-model="form.min_views" type="number" min="0" placeholder="1000" />
          </div>

          <div class="form-group">
            <label>Min. subskrypcji/obserwujących</label>
            <input v-model="form.min_subscribers" type="number" min="0" placeholder="5000" />
          </div>
        </div>

        <div class="form-group">
          <label>Maksymalna liczba filmów na twórcę</label>
          <input v-model="form.max_videos_per_creator" type="number" min="1" placeholder="1" />
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Maksymalna liczba zgłoszeń dziennie</label>
            <input v-model="form.max_submissions_per_day" type="number" min="1" placeholder="Bez limitu" />
          </div>
          <div class="form-group checkbox-group">
            <label>
              <input type="checkbox" v-model="form.rollover_remaining_budget" />
              Przenoś niewykorzystany budżet
            </label>
          </div>
        </div>

        <div class="form-group">
          <label>Wymagania platform (JSON)</label>
          <textarea v-model="form.platform_requirements_str" rows="2" placeholder='{"YouTube": {"min_subscribers": 1000}}'></textarea>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Data rozpoczęcia</label>
            <input v-model="form.start_date" type="datetime-local" />
          </div>
          <div class="form-group">
            <label>Data zakończenia</label>
            <input v-model="form.end_date" type="datetime-local" />
          </div>
        </div>

        <div class="form-group">
          <label>Linki social media (JSON)</label>
          <textarea v-model="form.social_media_links_str" rows="2" placeholder='{"instagram": "https://instagram.com/...", "youtube": "https://youtube.com/..."}'></textarea>
        </div>
      </fieldset>

      <!-- Sekcja 4: Rozliczenia i Stawki -->
      <fieldset>
        <legend>4. Rozliczenie i Wynagrodzenie</legend>

        <div class="grid-2">
          <div class="form-group">
            <label>Stawka za Short / TikTok (PLN)</label>
            <input v-model="form.short_payout" type="number" step="0.01" min="0" placeholder="200.00" />
          </div>

          <div class="form-group">
            <label>Stawka za Długie Wideo / YouTube (PLN)</label>
            <input v-model="form.long_payout" type="number" step="0.01" min="0" placeholder="800.00" />
          </div>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Stawka za 1000 wyświetleń (CPM PLN)</label>
            <input v-model="form.payout_per_views" type="number" step="0.01" min="0" max="99999999.99" placeholder="15.00" />
          </div>

          <div class="form-group">
            <label>Krok rozliczenia wyświetleń</label>
            <input v-model="form.views_unit_step" type="number" min="1" placeholder="1000" />
          </div>

          <div class="form-group">
            <label>Stawka za kliknięcie w link (CPC PLN)</label>
            <input v-model="form.payout_per_click" type="number" step="0.01" min="0" max="99999999.99" placeholder="1.50" />
          </div>
        </div>
      </fieldset>

      <button type="submit" class="btn-submit" :disabled="loading">
        {{ loading ? 'Utworzenie kampanii...' : 'Utwórz Kampanię' }}
      </button>

    </form>
  </div>
</template>

