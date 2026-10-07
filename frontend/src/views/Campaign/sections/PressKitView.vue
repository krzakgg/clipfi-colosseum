<script setup>
import { ref } from 'vue'

const coverFailed = ref(false)

defineProps({
  campaign: { type: Object, required: true }, galleryImages: { type: Array, required: true }, displayImage: { type: String, default: '' },
  pressKitDownloadUrl: { type: String, default: '' }, formatDate: { type: Function, required: true }, formatJson: { type: Function, required: true },
  isCompanyOwner: { type: Boolean, required: true }, uploadLoading: { type: Boolean, required: true }, uploadError: { type: String, default: '' }
})
const emit = defineEmits(['upload-press-kit'])
</script>

<template>
  <section class="press-kit-layout">
    <main class="press-kit-main">
      <article class="press-panel featured-video-panel"><div class="press-panel-heading"><h2>Featured Video</h2><a v-if="pressKitDownloadUrl" class="press-download" :href="pressKitDownloadUrl" download>Download <span>↓</span></a></div>
        <a v-if="campaign.press_kit_url" class="featured-video" :href="campaign.press_kit_url" target="_blank" rel="noopener" aria-label="Open Press Kit"><img v-if="displayImage" :src="displayImage" :alt="`Campaign preview for ${campaign.title}`" /><span class="play-button">▶</span></a><div v-else class="featured-video empty-video"><span>No featured material</span></div>
      </article>
      <article class="press-panel gallery-panel"><div class="press-panel-heading"><h2>Gallery</h2><span class="press-count">{{ galleryImages.length }} images</span></div><div v-if="galleryImages.length" class="press-gallery-grid"><a v-for="(image, index) in galleryImages" :key="`${image}-${index}`" class="press-gallery-item" :href="image" target="_blank" rel="noopener"><img :src="image" :alt="`Obraz galerii ${index + 1}`" /><span>↓</span></a></div><div v-else class="press-empty-state">No gallery images.</div></article>
      <article class="press-panel content-panel"><div class="press-panel-heading"><h2>Content</h2><span class="press-filter">All types⌄</span></div>
        <a v-if="pressKitDownloadUrl" class="content-file" :href="pressKitDownloadUrl" download><span class="file-type file-type-pdf">PDF</span><span class="file-details"><strong>Press Kit</strong><small>Brand materials</small></span><span class="file-size">Press kit</span><span class="content-download">Download <b>↓</b></span></a>
        <a v-else-if="campaign.press_kit_url" class="content-file external-content-file" :href="campaign.press_kit_url" target="_blank" rel="noopener"><span class="file-type file-type-link">↗</span><span class="file-details"><strong>Press Kit</strong><small>External link</small></span><span class="content-open">Open link</span></a>
        <div v-else class="press-empty-state">No additional files.</div><p class="platform-requirements">{{ formatJson(campaign.platform_requirements) }}</p>
        <label v-if="isCompanyOwner" class="press-upload"><input type="file" @change="emit('upload-press-kit', $event)" :disabled="uploadLoading" /><span class="upload-icon">↑</span><span><strong>{{ uploadLoading ? 'Uploading...' : 'Upload new content' }}</strong><small>Add a file, image or video</small></span></label><p v-if="uploadError" class="press-upload-error">{{ uploadError }}</p>
      </article>
    </main>
    <aside class="press-kit-sidebar"><article class="press-panel campaign-preview-card"><div class="press-cover" :class="{ 'empty-image': !displayImage || coverFailed }"><img v-if="displayImage && !coverFailed" :src="displayImage" :alt="`Campaign image ${campaign.title}`" @error="coverFailed = true" /><span v-else>No campaign image</span></div><h2>{{ campaign.title }}</h2><p v-if="campaign.product_description">{{ campaign.product_description }}</p><p v-else-if="campaign.description" class="rich-text-rendered" v-html="campaign.description"></p><p v-else>No campaign description.</p><dl class="press-meta"><div><dt>Developer</dt><dd>{{ campaign.company_name || '—' }}</dd></div><div><dt>Release Date</dt><dd>{{ formatDate(campaign.start_date) }}</dd></div></dl><h3>Tags</h3><div class="press-tags"><span v-for="language in (campaign.languages || [])" :key="language">{{ language }}</span><span v-if="!campaign.languages?.length">Campaign</span></div><h3 v-if="campaign.social_media_links">Socials</h3><div v-if="campaign.social_media_links" class="press-socials"><a v-for="(url, platform) in campaign.social_media_links" :key="platform" :href="url" target="_blank" rel="noopener"><span>{{ platform }}</span><b>→</b></a></div></article></aside>
  </section>
</template>
