<script setup>
import { computed, toRef } from 'vue'
import instagramIcon from '../../../assets/dropbox/Details/assets/icons8-instagram-96.png'
import twitchIcon from '../../../assets/dropbox/Overview/Assets/icons8-twitch-96.png'
import tiktokIcon from '../../../assets/dropbox/Overview/Assets/icons8-tiktok-96.png'
import xIcon from '../../../assets/dropbox/Details/assets/icons8-x-96.png'
import youtubeIcon from '../../../assets/dropbox/Details/assets/icons8-youtube-96.png'
import discordIcon from '../../../assets/dropbox/Details/assets/icons8-discord-new-96.png'
import steamIcon from '../../../assets/dropbox/Details/assets/icons8-steam-96.png'
import websiteIcon from '../../../assets/dropbox/Details/assets/Web--Streamline-Core-Remix.png'

const props = defineProps({
  campaign: { type: Object, required: true },
  galleryImages: { type: Array, required: true },
  displayImage: { type: String, default: '' },
  formatDate: { type: Function, required: true },
  selectedImage: { type: String, default: '' }
})

const campaign = toRef(props, 'campaign')
const galleryImages = toRef(props, 'galleryImages')
const displayImage = toRef(props, 'displayImage')
const formatDate = toRef(props, 'formatDate')
const selectedImage = toRef(props, 'selectedImage')

const emit = defineEmits(['select-image'])

const socialIcons = {
  instagram: instagramIcon,
  tiktok: tiktokIcon,
  twitch: twitchIcon,
  x: xIcon,
  youtube: youtubeIcon,
  discord: discordIcon,
  steam: steamIcon,
  website: websiteIcon
}

const getSocialIcon = platform => {
  const normalizedPlatform = String(platform).toLowerCase()
  return socialIcons[normalizedPlatform] || (normalizedPlatform === 'twitter' ? xIcon : '')
}

const getSocialLabel = platform => ({
  steam: 'View on Steam',
  website: 'View website',
  instagram: 'Instagram',
  twitter: 'X',
  x: 'X',
  youtube: 'YouTube',
  twitch: 'Twitch',
  tiktok: 'TikTok',
  discord: 'Discord'
}[String(platform).toLowerCase()] || String(platform))

const isFeaturedSocial = platform => ['steam', 'website'].includes(String(platform).toLowerCase())

const orderedSocialLinks = computed(() => Object.entries(campaign.value.social_media_links || {}).sort(([first], [second]) => {
  const priority = ['steam', 'website']
  return (priority.indexOf(String(first).toLowerCase()) + 1 || 99) - (priority.indexOf(String(second).toLowerCase()) + 1 || 99)
}))
</script>

<template>
  <section class="about-layout" id="campaign-about">
    <!-- Główna zawartość "About this game" po lewej -->
    <main class="about-main">
      <article class="info-card about-card">
        <h2>About this game</h2>

        <div v-if="campaign.description" class="campaign-description rich-text-rendered" v-html="campaign.description"></div>
        
        <p v-else class="feature-empty-state">
          <strong>No campaign description available.</strong>
          The campaign owner has not added a description yet.
        </p>

        <p v-if="campaign.product_description" class="campaign-product-description">{{ campaign.product_description }}</p>
      </article>
    </main>

    <!-- Prawy panel boczny z informacjami o grze -->
    <aside class="about-sidebar" id="campaign-details">
      <article class="campaign-sidebar-card">
        <!-- Obrazek nagłówka gry -->
        <div class="campaign-sidebar-image" :class="{ 'empty-image': !displayImage }">
          <img v-if="displayImage" :src="displayImage" :alt="`Campaign artwork for ${campaign.title}`" />
          <div v-else class="image-placeholder">No campaign artwork available.</div>
        </div>

        <div class="sidebar-card-content">
          <h2 class="sidebar-game-title">{{ campaign.game_name || campaign.title || 'Untitled campaign' }}</h2>
          
          <p class="sidebar-game-desc">
            {{ campaign.product_description || 'No product description available.' }}
          </p>

          <!-- Tabela metadanych -->
          <dl class="campaign-sidebar-meta">
            <div>
              <dt>Developer</dt>
              <dd>{{ campaign.company_name || campaign.developer || 'Not specified' }}</dd>
            </div>
            <div>
              <dt>Publisher</dt>
              <dd>{{ campaign.publisher || 'Not specified' }}</dd>
            </div>
            <div>
              <dt>Release Date</dt>
              <dd>{{ formatDate(campaign.start_date) }}</dd>
            </div>
            <div v-if="campaign.total_budget">
              <dt>Budget</dt>
              <dd>{{ campaign.total_budget }} PLN</dd>
            </div>
          </dl>

          <!-- Sekcja Tagi -->
          <div class="sidebar-section">
            <h3>Tags</h3>
            <div class="press-tags">
              <template v-if="campaign.tags?.length">
                <span v-for="tag in campaign.tags" :key="tag">{{ tag }}</span>
              </template>
              <template v-else>
                <span class="state-msg">No tags added.</span>
              </template>
            </div>
          </div>

          <!-- Sekcja Socials -->
          <div class="sidebar-section">
            <h3 class="socials-heading">Socials</h3>
            <div class="press-socials">
              <template v-if="orderedSocialLinks.length">
                <a
                  v-for="([platform, url], index) in orderedSocialLinks"
                  :key="platform"
                  :class="{
                    'featured-social': isFeaturedSocial(platform),
                    'social-divider': index > 0 && !isFeaturedSocial(platform) && isFeaturedSocial(orderedSocialLinks[index - 1][0])
                  }"
                  :href="url"
                  target="_blank"
                  rel="noopener"
                >
                  <span class="social-platform">
                    <img v-if="getSocialIcon(platform)" class="social-icon" :src="getSocialIcon(platform)" :alt="`${getSocialLabel(platform)} icon`" />
                    <span>{{ getSocialLabel(platform) }}</span>
                  </span>
                  <b aria-hidden="true">→</b>
                </a>
              </template>
              <template v-else>
                <span class="state-msg">No social links added.</span>
              </template>
            </div>
          </div>
        </div>
      </article>
    </aside>
  </section>
</template>