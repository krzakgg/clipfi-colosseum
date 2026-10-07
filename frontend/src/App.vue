<script setup>
import { onMounted, ref } from 'vue'
import CampaignList from './views/Campaign/CampaignList.vue'
import CreateCampaign from './views/Campaign/CreateCampaign.vue'
import EditCampaign from './views/Campaign/EditCampaign.vue'
import CampaignDetails from './views/Campaign/CampaignDetails.vue'
import Login from './views/Auth/Login.vue'
import Wallet from './views/Wallet/Wallet.vue'
import homeIcon from './assets/dropbox/Overview/Assets/Home-4--Streamline-Core-Remix.png'
import gamesIcon from './assets/dropbox/Overview/Assets/Controller-1--Streamline-Core-Remix.png'
import overviewIcon from './assets/dropbox/Overview/Assets/Wave-Signal-Square--Streamline-Core-Remix.png'
import creatorsIcon from './assets/dropbox/Overview/Assets/User-Multiple-Group--Streamline-Core-Remix.png'
import submissionsIcon from './assets/dropbox/Overview/Assets/Upload-File--Streamline-Core-Remix.png'
import requestsIcon from './assets/dropbox/Overview/Assets/Empty-Clipboard--Streamline-Core-Remix.png'
import keysIcon from './assets/dropbox/Overview/Assets/Key--Streamline-Solar (1).png'
import budgetIcon from './assets/dropbox/Overview/Assets/Coins-Stack--Streamline-Core-Remix.png'
import detailsIcon from './assets/dropbox/Overview/Assets/Magnifying-Glass-Circle--Streamline-Core-Remix.png'
import notificationsIcon from './assets/dropbox/Overview/Assets/Ringing-Bell-Notification--Streamline-Core-Remix.png'
import announcementIcon from './assets/dropbox/Overview/Assets/Announcement-Megaphone--Streamline-Core-Remix.png'
import editIcon from './assets/dropbox/Details/assets/New-File--Streamline-Core-Remix.png'
import createIcon from './assets/dropbox/Overview/Assets/Add-Circle--Streamline-Core-Remix.png'

const session = ref(JSON.parse(localStorage.getItem('waggi_session') || 'null'))
const currentTab = ref('list')
const editCampaignId = ref(null)
const detailsCampaignId = ref(null)
const campaigns = ref([])
const selectedCampaignId = ref('')
const selectedCampaignTitle = ref('')
const detailsSection = ref('about')

const fetchCampaigns = async () => {
  try {
    const response = await fetch('http://localhost:8000/api/campaigns')
    if (response.ok) campaigns.value = await response.json()
  } catch (error) {
    console.error('Failed to load campaigns for the sidebar.', error)
  }
}

// Open the campaign editor.
const handleEditCampaign = (id) => {
  editCampaignId.value = id
  currentTab.value = 'edit'
}

// Return to the campaign list after creation.
const handleCampaignCreated = () => {
  currentTab.value = 'list'
}

const handleViewCampaign = (id) => {
  detailsCampaignId.value = id
  selectedCampaignId.value = String(id)
  selectedCampaignTitle.value = ''
  detailsSection.value = 'about'
  currentTab.value = 'details'
}

const handleCampaignSelection = () => {
  if (!selectedCampaignId.value) return
  handleViewCampaign(Number(selectedCampaignId.value))
}

const handleCampaignLoaded = (title) => {
  selectedCampaignTitle.value = title
}

const openCampaignSection = (section) => {
  if (!detailsCampaignId.value) {
    currentTab.value = 'list'
    return
  }
  detailsSection.value = section
  currentTab.value = 'details'
}

const handleDetailsEdit = (id) => {
  editCampaignId.value = id
  currentTab.value = 'edit'
}

const openEditor = () => {
  if (!editCampaignId.value) editCampaignId.value = detailsCampaignId.value || campaigns.value[0]?.id || null
  currentTab.value = 'edit'
}

const handleLoggedIn = (data) => {
  session.value = data
  currentTab.value = 'list'
}

const logout = () => {
  localStorage.removeItem('waggi_session')
  session.value = null
}

onMounted(fetchCampaigns)
</script>

<template>
  <Login v-if="!session" @logged-in="handleLoggedIn" />

  <div v-else class="app-layout">
    <aside class="app-sidebar">
      <div class="brand">LOGO</div>

      <nav class="sidebar-nav">
        <div class="nav-section">
          <span class="nav-label">GENERAL</span>
          <button @click="currentTab = 'list'">
            <img class="nav-icon" :src="homeIcon" alt="" />
            <span>Home</span>
          </button>
          <button class="sidebar-game-button" @click="currentTab = 'list'">
            <img class="nav-icon" :src="gamesIcon" alt="" />
            <span>Games</span>
          </button>
          <select v-model="selectedCampaignId" class="sidebar-game-select" aria-label="Select campaign" @change="handleCampaignSelection">
            <option value="">Select campaign</option>
            <option v-for="campaign in campaigns" :key="campaign.id" :value="String(campaign.id)">
              #{{ campaign.id }} {{ campaign.title }}
            </option>
          </select>
        </div>

        <div class="nav-section">
          <span class="nav-label">CAMPAIGNS</span>
          <button :class="{ active: currentTab === 'list' }" @click="currentTab = 'list'">
            <img class="nav-icon" :src="overviewIcon" alt="" />
            <span>Overview</span>
            <span class="nav-chevron">›</span>
          </button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'creators' }" @click="openCampaignSection('creators')"><img class="nav-icon" :src="creatorsIcon" alt="" /><span>Creators</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'submissions' }" @click="openCampaignSection('submissions')"><img class="nav-icon" :src="submissionsIcon" alt="" /><span>Submissions</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'requests' }" @click="openCampaignSection('requests')"><img class="nav-icon" :src="requestsIcon" alt="" /><span>Key requests</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'keys' }" @click="openCampaignSection('keys')"><img class="nav-icon" :src="keysIcon" alt="" /><span>Game keys</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'escrow' }" @click="openCampaignSection('escrow')"><img class="nav-icon" :src="budgetIcon" alt="" /><span>Budget</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'details' }" @click="openCampaignSection('details')"><img class="nav-icon" :src="detailsIcon" alt="" /><span>Details</span><span class="nav-chevron">⌄</span></button>
          <button @click="currentTab = 'list'"><img class="nav-icon" :src="notificationsIcon" alt="" /><span>Notifications</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'wallet' }" @click="currentTab = 'wallet'"><svg class="nav-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 7.5A2.5 2.5 0 0 1 5.5 5H18v3" /><path d="M3 7.5V17a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-8a1 1 0 0 0-1-1H5.5A2.5 2.5 0 0 1 3 7.5Z" /><circle cx="16.5" cy="14" r="1" /></svg><span>Wallet</span><span class="nav-chevron">›</span></button>
          <button @click="currentTab = 'list'"><img class="nav-icon" :src="announcementIcon" alt="" /><span>Announcement</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'edit' }" @click="openEditor">
            <img class="nav-icon" :src="editIcon" alt="" />
            <span>Edit</span>
          </button>
        </div>

        <div class="nav-section">
          <span class="nav-label">SET UP</span>
          <button :class="{ active: currentTab === 'create' }" @click="currentTab = 'create'">
            <img class="nav-icon" :src="createIcon" alt="" />
            <span>New Campaign</span>
          </button>
        </div>
      </nav>
    </aside>

    <div class="workspace-panel">
      <header class="top-bar">
        <div class="user-pill">
          <span class="user-avatar"></span>
          <span>{{ session.account_type === 'company' ? session.user.name : (session.user.full_name || session.user.username) }}</span>
        </div>
        <button class="logout-button" @click="logout">Log out</button>
      </header>

      <main class="page-shell">
        <CampaignList 
          v-if="currentTab === 'list'" 
          @edit-campaign="handleEditCampaign"
          @view-campaign="handleViewCampaign"
          @create-new="currentTab = 'create'"
        />

        <Wallet v-else-if="currentTab === 'wallet'" />

        <CampaignDetails
          v-else-if="currentTab === 'details'"
          :campaign-id="detailsCampaignId"
          :session="session"
          :initial-section="detailsSection"
          @back="currentTab = 'list'"
          @edit-campaign="handleDetailsEdit"
          @campaign-loaded="handleCampaignLoaded"
        />

        <CreateCampaign 
          v-else-if="currentTab === 'create'" 
          :session="session"
          @campaign-created="handleCampaignCreated"
        />

        <div v-else-if="currentTab === 'edit'" class="edit-wrapper">
          <div class="selector-bar">
            <label>Selected campaign ID: </label>
            <input type="number" v-model.number="editCampaignId" min="1" />
          </div>
          <EditCampaign :campaign-id="editCampaignId" :session="session" />
        </div>

      </main>
    </div>
  </div>
</template>
