<script setup>
import { ref, computed, onMounted } from 'vue'
import ApplyToCampaign from './ApplyToCampaign.vue'
import ManageApplication from './ManageApplication.vue'
import SubmitCampaignVideo from './SubmitCampaignVideo.vue'

const props = defineProps({
  campaignId: { type: Number, required: true },
  session: { type: Object, required: true }
})

const emit = defineEmits(['back', 'edit-campaign'])

const campaign = ref(null)
const selectedImage = ref('')
const loading = ref(true)
const errorMessage = ref('')

const galleryImages = computed(() => {
  if (!campaign.value) return []
  return [campaign.value.cover_image_url, ...(campaign.value.gallery_image_urls || [])].filter(Boolean)
})

const displayImage = computed(() => selectedImage.value || galleryImages.value[0] || '')

const loadCampaign = async () => {
  loading.value = true
  errorMessage.value = ''
  try {
    const response = await fetch(`http://localhost:8000/api/campaigns/${props.campaignId}`)
    if (!response.ok) throw new Error('Nie znaleziono kampanii o podanym ID')
    campaign.value = await response.json()
    selectedImage.value = galleryImages.value[0] || ''
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    loading.value = false
  }
}

const formatDate = (date) => date ? new Date(date).toLocaleDateString('pl-PL') : 'Nie określono'

const isCompanyOwner = computed(() => (
  props.session.account_type === 'company' &&
  campaign.value?.company_id === props.session.user.id
))

onMounted(loadCampaign)
</script>

<template>
  <div class="details-container">
    <div class="details-toolbar">
      <button class="btn-back" @click="emit('back')">← Wróć do listy</button>
      <button v-if="isCompanyOwner" class="btn-edit" @click="emit('edit-campaign', campaign.id)">✏️ Edytuj kampanię</button>
    </div>

    <div v-if="loading" class="state-msg">Wczytywanie szczegółów kampanii...</div>
    <div v-else-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

    <template v-else-if="campaign">
      <section class="hero-section">
        <div class="hero-copy">
          <span class="eyebrow">Kampania #{{ campaign.id }}</span>
          <h1>{{ campaign.title }}</h1>
          <span :class="['badge', campaign.is_private ? 'badge-private' : 'badge-public']">
            {{ campaign.is_private ? 'Prywatna' : 'Publiczna' }}
          </span>
          <p>{{ campaign.description || 'Brak krótkiego opisu kampanii.' }}</p>
        </div>
        <div class="hero-image" :class="{ 'empty-image': !displayImage }">
          <img v-if="displayImage" :src="displayImage" :alt="`Obraz kampanii ${campaign.title}`" />
          <span v-else>Brak obrazu tytułowego</span>
        </div>
      </section>

      <section v-if="galleryImages.length > 1" class="gallery-section">
        <div class="section-heading">
          <h2>Galeria</h2>
          <span>{{ galleryImages.length }} obrazów</span>
        </div>
        <div class="gallery-grid">
          <button
            v-for="(image, index) in galleryImages"
            :key="`${image}-${index}`"
            class="gallery-thumb"
            :class="{ selected: image === displayImage }"
            @click="selectedImage = image"
          >
            <img :src="image" :alt="`Podgląd obrazu ${index + 1}`" />
          </button>
        </div>
      </section>

      <section class="info-grid">
        <article class="info-card">
          <h2>Opis kampanii</h2>
          <p>{{ campaign.product_description || 'Brak dodatkowego opisu produktu.' }}</p>
          <h3>Wytyczne marki</h3>
          <p>{{ campaign.brand_guidelines || 'Brak wytycznych.' }}</p>
        </article>

        <article class="info-card">
          <h2>Najważniejsze informacje</h2>
          <dl>
            <div><dt>Budżet całkowity</dt><dd>{{ campaign.total_budget }} PLN</dd></div>
            <div><dt>Budżet na twórcę</dt><dd>{{ campaign.budget_per_creator || 'Do ustalenia' }}{{ campaign.budget_per_creator ? ' PLN' : '' }}</dd></div>
            <div><dt>Języki</dt><dd>{{ campaign.languages?.join(', ') || 'Nie określono' }}</dd></div>
            <div><dt>Termin</dt><dd>{{ formatDate(campaign.start_date) }} - {{ formatDate(campaign.end_date) }}</dd></div>
            <div><dt>Minimalne wyświetlenia</dt><dd>{{ campaign.min_views || 0 }}</dd></div>
            <div><dt>Minimalni obserwujący</dt><dd>{{ campaign.min_subscribers || 0 }}</dd></div>
          </dl>
        </article>
      </section>

      <ApplyToCampaign
        v-if="props.session.account_type === 'creator'"
        :campaign-id="campaign.id"
        :creator-id="props.session.user.id"
      />
      <SubmitCampaignVideo
        v-if="props.session.account_type === 'creator'"
        :campaign-id="campaign.id"
        :creator-id="props.session.user.id"
      />
      <ManageApplication
        v-else-if="isCompanyOwner"
        :campaign-id="campaign.id"
        :company-id="props.session.user.id"
      />
    </template>
  </div>
</template>

