<script setup>
defineProps({
  campaign: { type: Object, required: true },
  galleryImages: { type: Array, required: true },
  displayImage: { type: String, default: '' },
  formatDate: { type: Function, required: true },
  selectedImage: { type: String, default: '' }
})
const emit = defineEmits(['select-image'])
</script>

<template>
  <section v-if="galleryImages.length > 1" class="gallery-section">
    <div class="section-heading"><h2>Galeria</h2><span>{{ galleryImages.length }} images</span></div>
    <div class="gallery-grid">
      <button v-for="(image, index) in galleryImages" :key="`${image}-${index}`" class="gallery-thumb" :class="{ selected: image === selectedImage }" @click="emit('select-image', image)">
        <img :src="image" :alt="`Gallery image ${index + 1}`" />
      </button>
    </div>
  </section>

  <section class="about-layout" id="campaign-about">
    <main class="about-main"><article class="info-card about-card">
      <h2>About the campaign</h2>
      <p class="campaign-tagline">{{ campaign.description || 'Campaign and product overview.' }}</p>
      <p>{{ campaign.product_description || 'No additional product description.' }}</p>
    </article></main>
    <aside class="about-sidebar" id="campaign-details"><article class="campaign-sidebar-card">
      <div class="campaign-sidebar-image" :class="{ 'empty-image': !displayImage }"><img v-if="displayImage" :src="displayImage" :alt="`Campaign artwork for ${campaign.title}`" /><span v-else>No campaign image</span></div>
      <h2>{{ campaign.title }}</h2><p>{{ campaign.product_description || campaign.description || 'No campaign description.' }}</p>
      <dl class="campaign-sidebar-meta"><div><dt>Developer</dt><dd>{{ campaign.company_name || 'Campaign team' }}</dd></div><div><dt>Release date</dt><dd>{{ formatDate(campaign.start_date) }}</dd></div><div><dt>Budget</dt><dd>{{ campaign.total_budget }} PLN</dd></div></dl>
      <h3>Tags</h3><div class="press-tags"><span v-for="language in (campaign.languages || [])" :key="language">{{ language }}</span><span v-if="!campaign.languages?.length">Campaign</span></div>
      <template v-if="campaign.social_media_links"><h3>Socials</h3><div class="press-socials"><a v-for="(url, platform) in campaign.social_media_links" :key="platform" :href="url" target="_blank" rel="noopener"><span>{{ platform }}</span><b>→</b></a></div></template>
    </article></aside>
  </section>
</template>
