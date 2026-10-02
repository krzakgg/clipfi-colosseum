<script setup>
import { ref, reactive, onMounted, computed, watch } from 'vue'
import { uploadImages } from '../../utils/uploadImage'
import RichTextEditor from '../../components/RichTextEditor.vue'

const props = defineProps({
  session: {
    type: Object,
    default: null
  }
})

const emit = defineEmits(['campaign-created'])

const loading = ref(false)
const successMessage = ref('')
const errorMessage = ref('')
const companies = ref([])
const coverFile = ref(null)
const galleryFiles = ref([])
const coverPreview = ref('')
const galleryPreviews = ref([])
const currentStep = ref(1)
const totalSteps = 4
const formRef = ref(null)
const isCompanySession = computed(() => props.session?.account_type === 'company')
const currentCompanyId = computed(() => Number(props.session?.user?.id || 0))
const AVAILABLE_LANGUAGES = ['PL', 'EN', 'DE', 'FR', 'ES', 'IT', 'NL', 'PT', 'CS', 'SK', 'TR', 'HU', 'RO', 'UA', 'RU', 'EL', 'FI', 'SV', 'DA', 'NO', 'IS', 'JA', 'KO', 'ZH', 'AR', 'HE', 'ID', 'MS', 'TH', 'VI', 'BN', 'HI', 'UR']
const normalizeLanguageValue = (value) => value ? String(value).trim().toUpperCase() : ''
const normalizeTagValue = (value) => String(value || '').trim()
const getUniqueLanguages = (values = []) => [...new Set((values || []).map(normalizeLanguageValue).filter(Boolean))]
const getUniqueTags = (values = []) => [...new Set((values || []).map(normalizeTagValue).filter(Boolean))]
const splitTagInput = (value) => value.split(',').map(normalizeTagValue).filter(Boolean)

const goToNextStep = () => {
  if (!formRef.value?.reportValidity()) return
  if (currentStep.value < totalSteps) currentStep.value += 1
}

const goToPreviousStep = () => {
  if (currentStep.value > 1) currentStep.value -= 1
}

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
  languages: ['PL'],
  tags: [],
  tagInput: '',
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

const syncSessionCompany = () => {
  if (isCompanySession.value && currentCompanyId.value) {
    form.company_id = String(currentCompanyId.value)
  }
}

watch(() => props.session, syncSessionCompany, { immediate: true })
onMounted(() => {
  fetchCompanies()
  syncSessionCompany()
})

const toggleLanguage = (language) => {
  const normalized = normalizeLanguageValue(language)
  if (!normalized) return

  const current = new Set(form.languages)
  if (current.has(normalized)) current.delete(normalized)
  else current.add(normalized)

  form.languages = [...current].sort((a, b) => AVAILABLE_LANGUAGES.indexOf(a) - AVAILABLE_LANGUAGES.indexOf(b))
}

const addTag = () => {
  const nextTags = splitTagInput(form.tagInput)
  if (!nextTags.length) return

  const preparedTags = getUniqueTags([...form.tags, ...nextTags])
  form.tags = preparedTags
  form.tagInput = ''
}

const handleTagInputKeydown = (event) => {
  if (event.key === 'Enter' || event.key === ',') {
    event.preventDefault()
    addTag()
  }
}

const removeTag = (tag) => {
  form.tags = form.tags.filter(item => item !== tag)
}

const handleSubmit = async () => {
  loading.value = true
  successMessage.value = ''
  errorMessage.value = ''

  try {
    const uploadedCover = coverFile.value ? (await uploadImages([coverFile.value]))[0] : form.cover_image_url
    const uploadedGallery = galleryFiles.value.length ? await uploadImages(galleryFiles.value) : []

    const payload = {
      company_id: isCompanySession.value ? currentCompanyId.value : Number(form.company_id || 0),
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

      languages: getUniqueLanguages(form.languages),
      tags: getUniqueTags(form.tags),
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
      company_id: isCompanySession.value && currentCompanyId.value ? String(currentCompanyId.value) : '',
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
      languages: ['PL'],
      tags: [],
      tagInput: '',
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
    currentStep.value = 1

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
    <h2>Create a new campaign</h2>

    <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

    <div class="campaign-steps" aria-label="Campaign creation progress">
      <span v-for="step in totalSteps" :key="step" :class="{ active: currentStep === step, complete: currentStep > step }">
        {{ step }}
      </span>
    </div>

    <form ref="formRef" @submit.prevent="handleSubmit" class="campaign-form">
      
      <!-- Sekcja 1: Podstawowe informacje -->
      <fieldset v-if="currentStep === 1">
        <legend>1. Basic information</legend>
        
        <div class="form-group">
          <label>Company *</label>
          <select v-if="!isCompanySession" v-model="form.company_id" required>
            <option value="" disabled>-- Select a company --</option>
            <option v-for="company in companies" :key="company.id" :value="company.id">
              {{ company.name }} (ID: {{ company.id }})
            </option>
          </select>
          <input v-else :value="session?.user?.name || 'Current company'" type="text" readonly />
        </div>

        <div class="form-group">
          <label>Campaign title *</label>
          <input v-model="form.title" type="text" placeholder="e.g. Summer app promotion" required />
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Campaign status</label>
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
              Private campaign
            </label>
          </div>
        </div>

        <div class="form-group">
          <RichTextEditor v-model="form.description" label="Overview" placeholder="Short summary of the campaign goal..." />
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Cover image from device</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" @change="handleCoverSelected" />
            <img v-if="coverPreview" class="image-preview" :src="coverPreview" alt="Podgląd obrazu tytułowego" />
            <label>Or paste URL</label>
            <input v-model="form.cover_image_url" type="url" placeholder="https://.../cover.jpg" />
          </div>

          <div class="form-group">
            <label>Gallery from device</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple @change="handleGallerySelected" />
            <small>You can select up to 20 images at once.</small>
            <div v-if="galleryPreviews.length" class="image-preview-grid">
              <img v-for="preview in galleryPreviews" :key="preview" class="image-preview" :src="preview" alt="Podgląd obrazu galerii" />
            </div>
            <label>Or paste URLs separated by commas</label>
            <input v-model="form.gallery_image_urls_str" type="text" placeholder="https://.../1.jpg, https://.../2.jpg" />
          </div>
        </div>
      </fieldset>

      <!-- Step 2: Creator materials -->
      <fieldset v-if="currentStep === 2">
        <legend>2. Creator materials</legend>

        <div class="form-group">
          <label>Detailed product description</label>
          <textarea v-model="form.product_description" rows="3" placeholder="Describe the main product features..."></textarea>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Press kit URL</label>
            <input v-model="form.press_kit_url" type="url" placeholder="https://..." />
          </div>

          <div class="form-group">
            <RichTextEditor v-model="form.brand_guidelines" label="Brand guidelines" placeholder="Describe logo usage, colors, tone and content rules..." />
          </div>
        </div>
      </fieldset>

      <!-- Step 3: Budget and requirements -->
      <fieldset v-if="currentStep === 3">
        <legend>3. Budget and requirements</legend>

        <div class="grid-2">
          <div class="form-group">
            <label>Total budget (PLN) *</label>
            <input v-model="form.total_budget" type="number" step="0.01" min="0" max="9999999999.99" placeholder="10000.00" required />
          </div>

          <div class="form-group">
            <label>Budget per creator (PLN)</label>
            <input v-model="form.budget_per_creator" type="number" step="0.01" min="0" max="99999999.99" placeholder="1500.00" />
          </div>
          <div class="form-group">
            <label>Budget per time unit (PLN)</label>
            <input v-model="form.budget_per_time_unit" type="number" step="0.01" min="0" max="99999999.99" placeholder="500.00" />
          </div>
        </div>

        <div class="form-group">
          <label>Budget by language (JSON)</label>
          <textarea v-model="form.budget_per_language_str" rows="2" placeholder='{"PL": 1000, "EN": 1200}'></textarea>
        </div>

        <div class="form-group">
          <label>Campaign languages</label>
          <div class="chip-list">
            <button
              v-for="language in AVAILABLE_LANGUAGES"
              :key="language"
              type="button"
              class="chip-button"
              :class="{ active: form.languages.includes(language) }"
              @click="toggleLanguage(language)"
            >
              {{ language }}
            </button>
          </div>
        </div>

        <div class="form-group">
          <label>Campaign tags</label>
          <div class="tag-input-row">
            <input v-model="form.tagInput" type="text" placeholder="e.g. gaming, beauty" @keydown="handleTagInputKeydown" />
            <button type="button" class="btn-secondary" @click="addTag">Add</button>
          </div>
          <div v-if="form.tags.length" class="chip-list compact">
            <span v-for="tag in form.tags" :key="tag" class="tag-chip">
              {{ tag }}
              <button type="button" class="tag-chip-remove" @click="removeTag(tag)">×</button>
            </span>
          </div>
        </div>

        <div class="grid-3">
          <div class="form-group">
            <label>Min. views</label>
            <input v-model="form.min_views" type="number" min="0" placeholder="1000" />
          </div>

          <div class="form-group">
            <label>Min. subscribers/followers</label>
            <input v-model="form.min_subscribers" type="number" min="0" placeholder="5000" />
          </div>
        </div>

        <div class="form-group">
          <label>Maximum videos per creator</label>
          <input v-model="form.max_videos_per_creator" type="number" min="1" placeholder="1" />
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Maximum submissions per day</label>
            <input v-model="form.max_submissions_per_day" type="number" min="1" placeholder="Bez limitu" />
          </div>
          <div class="form-group checkbox-group">
            <label>
              <input type="checkbox" v-model="form.rollover_remaining_budget" />
              Carry over unused budget
            </label>
          </div>
        </div>

        <div class="form-group">
          <label>Platform requirements (JSON)</label>
          <textarea v-model="form.platform_requirements_str" rows="2" placeholder='{"YouTube": {"min_subscribers": 1000}}'></textarea>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Start date</label>
            <input v-model="form.start_date" type="datetime-local" />
          </div>
          <div class="form-group">
            <label>End date</label>
            <input v-model="form.end_date" type="datetime-local" />
          </div>
        </div>

        <div class="form-group">
          <label>Social media links (JSON)</label>
          <textarea v-model="form.social_media_links_str" rows="2" placeholder='{"steam": "https://store.steampowered.com/app/...", "instagram": "https://instagram.com/..."}'></textarea>
        </div>
      </fieldset>

      <!-- Step 4: Payouts and rates -->
      <fieldset v-if="currentStep === 4">
        <legend>4. Payouts and rates</legend>

        <div class="grid-2">
          <div class="form-group">
            <label>Short / TikTok payout (PLN)</label>
            <input v-model="form.short_payout" type="number" step="0.01" min="0" placeholder="200.00" />
          </div>

          <div class="form-group">
            <label>Long video / YouTube payout (PLN)</label>
            <input v-model="form.long_payout" type="number" step="0.01" min="0" placeholder="800.00" />
          </div>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>CPM payout for 1000 views (PLN)</label>
            <input v-model="form.payout_per_views" type="number" step="0.01" min="0" max="99999999.99" placeholder="15.00" />
          </div>

          <div class="form-group">
            <label>Views payout step</label>
            <input v-model="form.views_unit_step" type="number" min="1" placeholder="1000" />
          </div>

          <div class="form-group">
            <label>Link click payout (CPC PLN)</label>
            <input v-model="form.payout_per_click" type="number" step="0.01" min="0" max="99999999.99" placeholder="1.50" />
          </div>
        </div>
      </fieldset>

      <div class="campaign-navigation">
        <button v-if="currentStep > 1" type="button" class="btn-secondary" @click="goToPreviousStep">Back</button>
        <button v-if="currentStep < totalSteps" type="button" class="btn-submit" @click="goToNextStep">Next</button>
        <button v-else type="submit" class="btn-submit" :disabled="loading">
          {{ loading ? 'Creating campaign...' : 'Create campaign' }}
        </button>
      </div>

    </form>
  </div>
</template>
