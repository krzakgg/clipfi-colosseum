<script setup>
import { ref, reactive, onMounted, watch, computed } from 'vue'
import { uploadImages } from '../../utils/uploadImage'
import RichTextEditor from '../../components/RichTextEditor.vue'

const props = defineProps({
  campaignId: {
    type: Number,
    default: 1
  },
  session: {
    type: Object,
    default: null
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
  if (!value || !value.trim()) return null
  try {
    const parsed = JSON.parse(value)
    if (!parsed || Array.isArray(parsed) || typeof parsed !== 'object') throw new Error()
    return parsed
  } catch {
    throw new Error(`${label} must be a valid JSON object.`)
  }
}

const stringifyJson = (value) => value ? JSON.stringify(value, null, 2) : ''

const fetchCompanies = async () => {
  try {
    const res = await fetch('http://localhost:8000/api/companies')
    if (res.ok) companies.value = await res.json()
  } catch (err) {
    console.error('Failed to load companies:', err)
  }
}

const form = reactive({
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
  total_budget: 0,
  budget_per_creator: 0,
  budget_per_time_unit: 0,
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
  
  // Dedykowany obiekt na linki social media
  social_media_links: {
    instagram: '',
    twitter: '',
    steam: '',
    website: '',
    youtube: ''
  },

  short_payout: 0,
  long_payout: 0,
  payout_per_views: 0,
  views_unit_step: 1000,
  payout_per_click: 0
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

  form.tags = getUniqueTags([...form.tags, ...nextTags])
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

const loadCampaign = async () => {
  if (!props.campaignId) return
  fetching.value = true
  errorMessage.value = ''

  try {
    const res = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}`)
    if (!res.ok) throw new Error('Nie znaleziono kampanii o podanym ID')

    const data = await res.json()

    form.company_id = isCompanySession.value && currentCompanyId.value ? currentCompanyId.value : Number(data.company_id || 0)
    form.title = data.title || ''
    form.description = data.description || ''
    form.status = data.status || 'DRAFT'
    form.is_private = data.is_private || false
    form.cover_image_url = data.cover_image_url || ''
    form.gallery_image_urls_str = data.gallery_image_urls ? data.gallery_image_urls.join(', ') : ''
    form.product_description = data.product_description || ''
    form.press_kit_url = data.press_kit_url || ''
    form.brand_guidelines = data.brand_guidelines || ''
    form.total_budget = data.total_budget
    form.budget_per_creator = data.budget_per_creator || 0
    form.budget_per_time_unit = data.budget_per_time_unit || 0
    form.budget_per_language_str = stringifyJson(data.budget_per_language)
    form.languages = getUniqueLanguages(data.languages || ['PL'])
    form.tags = getUniqueTags(data.tags || [])
    form.tagInput = ''
    form.min_views = data.min_views || 0
    form.min_subscribers = data.min_subscribers || 0
    form.max_videos_per_creator = data.max_videos_per_creator || 1
    form.max_submissions_per_day = data.max_submissions_per_day || null
    form.platform_requirements_str = stringifyJson(data.platform_requirements)
    form.start_date = data.start_date ? data.start_date.slice(0, 16) : ''
    form.end_date = data.end_date ? data.end_date.slice(0, 16) : ''
    form.rollover_remaining_budget = data.rollover_remaining_budget || false
    
    // Mapowanie linków social media
    const links = data.social_media_links || {}
    form.social_media_links.instagram = links.instagram || ''
    form.social_media_links.twitter = links.twitter || ''
    form.social_media_links.steam = links.steam || ''
    form.social_media_links.website = links.website || ''
    form.social_media_links.youtube = links.youtube || ''


    if (data.payout_by_content_type) {
      form.short_payout = data.payout_by_content_type.Short || 0
      form.long_payout = data.payout_by_content_type.LongVideo || 0
    }
    form.payout_per_views = data.payout_per_views || 0
    form.views_unit_step = data.views_unit_step || 1000
    form.payout_per_click = data.payout_per_click || 0
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    fetching.value = false
  }
}

watch(() => props.campaignId, loadCampaign)

const syncSessionCompany = () => {
  if (isCompanySession.value && currentCompanyId.value) {
    form.company_id = currentCompanyId.value
  }
}

watch(() => props.session, syncSessionCompany, { immediate: true })

onMounted(async () => {
  await fetchCompanies()
  syncSessionCompany()
  await loadCampaign()
})

const handleUpdate = async () => {
  loading.value = true
  successMessage.value = ''
  errorMessage.value = ''

  try {
    const uploadedCover = coverFile.value ? (await uploadImages([coverFile.value]))[0] : form.cover_image_url
    const uploadedGallery = galleryFiles.value.length ? await uploadImages(galleryFiles.value) : []

    // Przygotowanie obiektu Social Media Links (usuwa puste pola)
    const cleanSocialLinks = {}
    if (form.social_media_links.instagram.trim()) cleanSocialLinks.instagram = form.social_media_links.instagram.trim()
    if (form.social_media_links.twitter.trim()) cleanSocialLinks.twitter = form.social_media_links.twitter.trim()
    if (form.social_media_links.steam.trim()) cleanSocialLinks.steam = form.social_media_links.steam.trim()
    if (form.social_media_links.website.trim()) cleanSocialLinks.website = form.social_media_links.website.trim()
    if (form.social_media_links.youtube.trim()) cleanSocialLinks.youtube = form.social_media_links.youtube.trim()

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
      budget_per_language: parseJsonField(form.budget_per_language_str, 'Budget per language'),
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

      social_media_links: Object.keys(cleanSocialLinks).length > 0 ? cleanSocialLinks : null,

      payout_by_content_type: {
        Short: form.short_payout ? parseFloat(form.short_payout) : 0,
        LongVideo: form.long_payout ? parseFloat(form.long_payout) : 0
      },
      payout_per_views: form.payout_per_views ? parseFloat(form.payout_per_views) : null,
      views_unit_step: parseInt(form.views_unit_step) || 1000,
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
      throw new Error(details || 'Failed to update the campaign')
    }

    const data = await response.json()
    successMessage.value = `Campaign "${data.title}" has been updated.`
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
    errorMessage.value = 'You can select up to 20 gallery images.'
  } else {
    errorMessage.value = ''
  }
  galleryFiles.value = selectedFiles.slice(0, 20)
  galleryPreviews.value = galleryFiles.value.map(file => URL.createObjectURL(file))
}
</script>

<template>
  <div class="edit-container">
    <h2>Edit campaign (ID: {{ campaignId }})</h2>

    <div v-if="fetching">Loading campaign data...</div>

    <template v-else>
      <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>
      <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

      <div class="campaign-steps" aria-label="Campaign edit progress">
        <span v-for="step in totalSteps" :key="step" :class="{ active: currentStep === step, complete: currentStep > step }">
          {{ step }}
        </span>
      </div>

      <form ref="formRef" @submit.prevent="handleUpdate" class="campaign-form">
        <fieldset v-if="currentStep === 1">
          <legend>Basic data</legend>
          
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
            <label>Campaign title</label>
            <input v-model="form.title" type="text" required />
          </div>
          
          <div class="grid-2">
            <div class="form-group">
              <label>Campaign status</label>
              <select v-model="form.status">
                <option value="DRAFT">Draft</option>
                <option value="ACTIVE">Active</option>
                <option value="PAUSED">Paused</option>
                <option value="COMPLETED">Completed</option>
                <option value="CANCELLED">Anulowana</option>
              </select>
            </div>
            <div class="form-group checkbox-group">
              <label><input type="checkbox" v-model="form.is_private" /> Private campaign</label>
            </div>
          </div>

          <div class="form-group">
            <RichTextEditor v-model="form.description" label="Campaign description" placeholder="Describe the campaign goal..." />
          </div>

          <div class="form-group">
            <RichTextEditor v-model="form.brand_guidelines" label="Brand guidelines" placeholder="Describe logo usage, colors, tone and content rules..." />
          </div>

          <div class="form-group">
            <label>Cover image from device</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" @change="handleCoverSelected" />
            <img v-if="coverPreview" class="image-preview" :src="coverPreview" alt="New cover image preview" />
            <label>Or paste URL</label>
            <input v-model="form.cover_image_url" type="url" placeholder="https://.../cover.jpg" />
          </div>

          <div class="form-group">
            <label>Gallery from device</label>
            <input type="file" accept="image/jpeg,image/png,image/webp,image/gif" multiple @change="handleGallerySelected" />
            <small>You can select up to 20 images at once.</small>
            <div v-if="galleryPreviews.length" class="image-preview-grid">
              <img v-for="preview in galleryPreviews" :key="preview" class="image-preview" :src="preview" alt="New gallery image preview" />
            </div>
            <label>Or paste URLs separated by commas</label>
            <input v-model="form.gallery_image_urls_str" type="text" placeholder="https://.../1.jpg, https://.../2.jpg" />
          </div>
        </fieldset>

        <fieldset v-if="currentStep === 2">
          <legend>Budget</legend>
          <div class="grid-2">
            <div class="form-group">
              <label>Total budget (PLN)</label>
              <input v-model="form.total_budget" type="number" step="0.01" min="0" max="9999999999.99" required />
            </div>
            <div class="form-group">
              <label>Budget per creator (PLN)</label>
              <input v-model="form.budget_per_creator" type="number" step="0.01" min="0" max="99999999.99" />
            </div>
            <div class="form-group">
              <label>Budget per time unit (PLN)</label>
              <input v-model="form.budget_per_time_unit" type="number" step="0.01" min="0" max="99999999.99" />
            </div>
          </div>
          <div class="form-group">
            <label>Budget by language (JSON)</label>
            <textarea v-model="form.budget_per_language_str" rows="2"></textarea>
          </div>
          <div class="form-group">
            <label>Views payout step</label>
            <input v-model="form.views_unit_step" type="number" min="1" />
          </div>
        </fieldset>

        <fieldset v-if="currentStep === 3">
          <legend>Requirements and materials</legend>
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

          <div class="grid-2">
            <div class="form-group">
              <label>Maximum videos per creator</label>
              <input v-model="form.max_videos_per_creator" type="number" min="1" />
            </div>
            <div class="form-group">
              <label>Maximum submissions per day</label>
              <input v-model="form.max_submissions_per_day" type="number" min="1" placeholder="No limit" />
            </div>
          </div>
          <div class="form-group">
            <label>Platform requirements (JSON)</label>
            <textarea v-model="form.platform_requirements_str" rows="2"></textarea>
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
          <div class="form-group checkbox-group">
            <label><input type="checkbox" v-model="form.rollover_remaining_budget" /> Carry over unused budget</label>
          </div>
        </fieldset>

        <fieldset v-if="currentStep === 4">
          <legend>Links and social media</legend>
          
          <div class="grid-2">
            <div class="form-group">
              <label>Steam URL</label>
              <input v-model="form.social_media_links.steam" type="url" placeholder="https://store.steampowered.com/app/..." />
            </div>

            <div class="form-group">
              <label>Instagram URL</label>
              <input v-model="form.social_media_links.instagram" type="url" placeholder="https://instagram.com/..." />
            </div>

            <div class="form-group">
              <label>Twitter / X URL</label>
              <input v-model="form.social_media_links.twitter" type="url" placeholder="https://x.com/..." />
            </div>
          </div>

          <div class="grid-2">
            <div class="form-group">
              <label>Website</label>
              <input v-model="form.social_media_links.website" type="url" placeholder="https://mojastrona.pl" />
            </div>

            <div class="form-group">
              <label>YouTube Channel / Video URL</label>
              <input v-model="form.social_media_links.youtube" type="url" placeholder="https://youtube.com/..." />
            </div>
          </div>

        </fieldset>

        <div class="campaign-navigation">
          <button v-if="currentStep > 1" type="button" class="btn-secondary" @click="goToPreviousStep">Back</button>
          <button v-if="currentStep < totalSteps" type="button" class="btn-submit" @click="goToNextStep">Next</button>
          <button v-else type="submit" class="btn-submit" :disabled="loading">
            {{ loading ? 'Saving...' : 'Save changes' }}
          </button>
        </div>
      </form>
    </template>
  </div>
</template>