<script setup>
import { onMounted, ref } from 'vue'
import CampaignList from './views/Campaign/CampaignList.vue'
import CreateCampaign from './views/Campaign/CreateCampaign.vue'
import EditCampaign from './views/Campaign/EditCampaign.vue'
import CampaignDetails from './views/Campaign/CampaignDetails.vue'
import Login from './views/Auth/Login.vue'
import Wallet from './views/Wallet/Wallet.vue'

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
            <span class="nav-icon">⌂</span>
            <span>Home</span>
          </button>
          <button class="sidebar-game-button" @click="currentTab = 'list'">
            <span class="nav-icon">◫</span>
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
            <span class="nav-icon">▧</span>
            <span>Overview</span>
            <span class="nav-chevron">›</span>
          </button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'creators' }" @click="openCampaignSection('creators')"><span class="nav-icon">♧</span><span>Creators</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'submissions' }" @click="openCampaignSection('submissions')"><span class="nav-icon">⇧</span><span>Submissions</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'requests' }" @click="openCampaignSection('requests')"><span class="nav-icon">□</span><span>Key requests</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'keys' }" @click="openCampaignSection('keys')"><span class="nav-icon">⚿</span><span>Game keys</span><span class="nav-chevron">›</span></button>
          <button @click="currentTab = 'list'"><span class="nav-icon">▤</span><span>Budget</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'details' && detailsSection === 'details' }" @click="openCampaignSection('details')"><span class="nav-icon">⊙</span><span>Details</span><span class="nav-chevron">⌄</span></button>
          <button @click="currentTab = 'list'"><span class="nav-icon">♧</span><span>Notifications</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'wallet' }" @click="currentTab = 'wallet'"><span class="nav-icon">◈</span><span>Wallet</span><span class="nav-chevron">›</span></button>
          <button @click="currentTab = 'list'"><span class="nav-icon">※</span><span>Announcement</span><span class="nav-chevron">›</span></button>
          <button :class="{ active: currentTab === 'edit' }" @click="currentTab = 'edit'">
            <span class="nav-icon">✎</span>
            <span>Edit</span>
          </button>
        </div>

        <div class="nav-section">
          <span class="nav-label">SET UP</span>
          <button :class="{ active: currentTab === 'create' }" @click="currentTab = 'create'">
            <span class="nav-icon">＋</span>
            <span>New Campaign</span>
          </button>
        </div>
      </nav>
    </aside>

    <div class="workspace-panel">
      <header class="top-bar">
        <div class="user-pill">
          <span class="user-avatar">◉</span>
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
