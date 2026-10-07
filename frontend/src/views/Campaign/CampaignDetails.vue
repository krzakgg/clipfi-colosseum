<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import aboutTabIcon from '../../assets/dropbox/Details/assets/Information-Circle--Streamline-Core-Remix.png'
import detailsTabIcon from '../../assets/dropbox/Details/assets/Magnifying-Glass-Circle--Streamline-Core-Remix (1).png'
import guidelinesTabIcon from '../../assets/dropbox/Details/assets/Manual-Book--Streamline-Core-Remix.png'
import resourcesTabIcon from '../../assets/dropbox/Details/assets/New-Folder--Streamline-Core-Remix.png'
import submissionsTabIcon from '../../assets/dropbox/Details/assets/Upload-File--Streamline-Core-Remix.png'
import escrowTabIcon from '../../assets/dropbox/Overview/Assets/Coins-Stack--Streamline-Core-Remix.png'
import AboutCampaignView from './sections/AboutCampaignView.vue'
import EscrowView from './sections/EscrowView.vue'
import CampaignDetailsView from './sections/CampaignDetailsView.vue'
import CreatorsView from './sections/CreatorsView.vue'
import GuidelinesView from './sections/GuidelinesView.vue'
import PressKitView from './sections/PressKitView.vue'
import SubmissionsView from './sections/SubmissionsView.vue'
import KeyRequestsView from './sections/KeyRequestsView.vue'
import GameKeysView from './sections/GameKeysView.vue'

const props = defineProps({ campaignId: { type: Number, required: true }, session: { type: Object, required: true }, initialSection: { type: String, default: 'about' } })
const emit = defineEmits(['back', 'edit-campaign', 'campaign-loaded'])
const campaign = ref(null)
const selectedImage = ref('')
const activeSection = ref('about')
const loading = ref(true)
const errorMessage = ref('')
const uploadLoading = ref(false)
const uploadError = ref('')
const creatorApplicationStatus = ref(null)
const creatorApplicationLoading = ref(false)

const galleryImages = computed(() => campaign.value ? [campaign.value.cover_image_url, ...(campaign.value.gallery_image_urls || [])].filter(Boolean) : [])
const displayImage = computed(() => selectedImage.value || galleryImages.value[0] || '')
const pressKitHost = computed(() => {
  if (!campaign.value?.press_kit_url) return ''
  try { return new URL(campaign.value.press_kit_url).hostname.toLowerCase() } catch { return '' }
})
const canDownloadPressKit = computed(() => {
  const host = pressKitHost.value
  return Boolean(host) && !['drive.google.com', 'docs.google.com', 'dropbox.com', 'www.dropbox.com'].some(blocked => host === blocked || host.endsWith(`.${blocked}`))
})
const pressKitDownloadUrl = computed(() => canDownloadPressKit.value ? `http://localhost:8000/api/campaigns/${props.campaignId}/press-kit/download` : '')
const guidelineItems = computed(() => (campaign.value?.brand_guidelines || '').split(/\r?\n+/).map(item => item.replace(/^[-•*]\s*/, '').trim()).filter(Boolean))
const brandGuidelines = computed(() => campaign.value?.brand_guidelines || '')
const talkingPoints = computed(() => Object.entries(campaign.value?.platform_requirements || {}).map(([platform, values]) => {
  const details = typeof values === 'object' && values !== null ? Object.entries(values).map(([key, value]) => `${key}: ${value}`).join(', ') : String(values)
  return `${platform}: ${details}`
}))
const isCompanyOwner = computed(() => props.session.account_type === 'company' && campaign.value?.company_id === props.session.user.id)
const canSubmitCampaignVideo = computed(() => props.session.account_type === 'creator' && creatorApplicationStatus.value === 'accepted')
const canApplyToCampaign = computed(() => props.session.account_type === 'creator' && !creatorApplicationLoading.value && !creatorApplicationStatus.value)
const formatDate = date => date ? new Date(date).toLocaleDateString('en-US') : 'Not specified'
const formatJson = value => value && Object.keys(value).length ? JSON.stringify(value) : 'No additional platform requirements.'

const loadCreatorApplication = async () => {
  creatorApplicationLoading.value = true
  try {
    const response = await fetch(`http://localhost:8000/api/applications/creator/${props.session.user.id}/campaign/${props.campaignId}`)
    creatorApplicationStatus.value = response.ok ? (await response.json()).status : null
  } catch { creatorApplicationStatus.value = null } finally { creatorApplicationLoading.value = false }
}

const loadCampaign = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}`)
    if (!response.ok) throw new Error('Campaign with this ID was not found')
    campaign.value = await response.json()
    emit('campaign-loaded', campaign.value.title)
    selectedImage.value = galleryImages.value[0] || ''
    if (props.session.account_type === 'creator') await loadCreatorApplication()
  } catch (error) { errorMessage.value = error.message } finally { loading.value = false }
}

const uploadPressKit = async event => {
  const file = event.target.files?.[0]
  event.target.value = ''
  if (!file) return
  uploadLoading.value = true
  uploadError.value = ''
  try {
    const formData = new FormData()
    formData.append('file', file)
    const response = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}/press-kit/upload`, { method: 'POST', body: formData })
    const data = await response.json()
    if (!response.ok) throw new Error(data.detail || 'Press Kit upload failed')
    campaign.value = data
  } catch (error) { uploadError.value = error.message } finally { uploadLoading.value = false }
}

onMounted(loadCampaign)
watch(() => props.initialSection, section => { activeSection.value = section }, { immediate: true })
</script>

<template>
  <div class="details-container">
    <div class="details-toolbar"><button class="btn-back" @click="emit('back')">← Back to campaigns</button><button v-if="isCompanyOwner" class="btn-edit" @click="emit('edit-campaign', campaign.id)">Edit campaign</button></div>
    <div v-if="loading" class="state-msg">Loading campaign details...</div>
    <div v-else-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>
    <template v-else-if="campaign">
      <section class="campaign-heading">
        <div class="campaign-heading-copy">
          <span class="eyebrow">Campaign #{{ campaign.id }}</span>
          <div class="campaign-title-row">
            <h1>{{ campaign.title }}</h1>
            <span :class="['status-badge', `status-${(campaign.status || 'DRAFT').toLowerCase()}`]">{{ campaign.status || 'DRAFT' }}</span>
          </div>
          <p class="campaign-heading-subtitle">{{ campaign.game_name || campaign.product_name || 'Campaign details' }}</p>
        </div>
        <div class="campaign-heading-meta">
          <span>{{ formatDate(campaign.start_date) }} - {{ formatDate(campaign.end_date) }}</span>
          <span :class="['badge', campaign.is_private ? 'badge-private' : 'badge-public']">{{ campaign.is_private ? 'Private' : 'Public' }}</span>
        </div>
      </section>
      <nav v-if="!['creators', 'submissions', 'requests', 'keys'].includes(activeSection)" class="campaign-tabs" aria-label="Campaign sections">
        <button type="button" class="campaign-tab" :class="{ active: activeSection === 'about' }" @click="activeSection = 'about'"><img class="tab-icon" :src="aboutTabIcon" alt="" /><span>About</span></button>
        <button type="button" class="campaign-tab" :class="{ active: activeSection === 'details' }" @click="activeSection = 'details'"><img class="tab-icon" :src="detailsTabIcon" alt="" /><span>Details</span></button>
        <button type="button" class="campaign-tab" :class="{ active: activeSection === 'guidelines' }" @click="activeSection = 'guidelines'"><img class="tab-icon" :src="guidelinesTabIcon" alt="" /><span>Guidelines</span></button>
        <button type="button" class="campaign-tab" :class="{ active: activeSection === 'resources' }" @click="activeSection = 'resources'"><img class="tab-icon" :src="resourcesTabIcon" alt="" /><span>Press Kit</span></button>
        <button type="button" class="campaign-tab" :class="{ active: activeSection === 'submissions' }" @click="activeSection = 'submissions'"><img class="tab-icon" :src="submissionsTabIcon" alt="" /><span>Submissions</span></button>
        <button type="button" class="campaign-tab" :class="{ active: activeSection === 'escrow' }" @click="activeSection = 'escrow'"><img class="tab-icon" :src="escrowTabIcon" alt="" /><span>Escrow</span></button>
      </nav>
      <AboutCampaignView v-if="activeSection === 'about'" :campaign="campaign" :gallery-images="galleryImages" :display-image="displayImage" :selected-image="selectedImage" :format-date="formatDate" @select-image="selectedImage = $event" />
      <CampaignDetailsView v-else-if="activeSection === 'details'" :campaign="campaign" :format-date="formatDate" />
      <GuidelinesView v-else-if="activeSection === 'guidelines'" :guideline-items="guidelineItems" :brand-guidelines="brandGuidelines" :talking-points="talkingPoints" />
      <PressKitView v-else-if="activeSection === 'resources'" :campaign="campaign" :gallery-images="galleryImages" :display-image="displayImage" :press-kit-download-url="pressKitDownloadUrl" :format-date="formatDate" :format-json="formatJson" :is-company-owner="isCompanyOwner" :upload-loading="uploadLoading" :upload-error="uploadError" @upload-press-kit="uploadPressKit" />
      <CreatorsView v-else-if="activeSection === 'creators'" :campaign="campaign" :session="session" :is-company-owner="isCompanyOwner" />
      <SubmissionsView v-else-if="activeSection === 'submissions'" :campaign="campaign" :session="session" :can-apply-to-campaign="canApplyToCampaign" :can-submit-campaign-video="canSubmitCampaignVideo" :creator-application-loading="creatorApplicationLoading" :creator-application-status="creatorApplicationStatus" :is-company-owner="isCompanyOwner" />
      <KeyRequestsView v-else-if="activeSection === 'requests'" :campaign-id="campaignId" :session="session" :is-company-owner="isCompanyOwner" />
      <GameKeysView v-else-if="activeSection === 'keys'" :campaign-id="campaignId" :session="session" :is-company-owner="isCompanyOwner" />
      <EscrowView v-else-if="activeSection === 'escrow'" :campaign-id="campaignId" :campaign="campaign" :session="session" :is-company-owner="isCompanyOwner" />
    </template>
  </div>
</template>
