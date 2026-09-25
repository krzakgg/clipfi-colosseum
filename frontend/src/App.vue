<script setup>
import { ref } from 'vue'
import CampaignList from './views/Campaign/CampaignList.vue'
import CreateCampaign from './views/Campaign/CreateCampaign.vue'
import EditCampaign from './views/Campaign/EditCampaign.vue'
import CampaignDetails from './views/Campaign/CampaignDetails.vue'
import TestSeeder from './views/Campaign/TestSeeder.vue'
import Login from './views/Auth/Login.vue'

const session = ref(JSON.parse(localStorage.getItem('waggi_session') || 'null'))
const currentTab = ref('list')
const editCampaignId = ref(null)
const detailsCampaignId = ref(null)

// Reakcja na kliknięcie "Edytuj" w tabeli
const handleEditCampaign = (id) => {
  editCampaignId.value = id
  currentTab.value = 'edit'
}

// Przejście do widoku listy po pomyślnym dodaniu kampanii
const handleCampaignCreated = () => {
  currentTab.value = 'list'
}

const handleViewCampaign = (id) => {
  detailsCampaignId.value = id
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
</script>

<template>
  <Login v-if="!session" @logged-in="handleLoggedIn" />

  <div v-else class="app-layout">
    <nav class="nav-bar">
      <span class="session-label">
        {{ session.account_type === 'company' ? session.user.name : (session.user.full_name || session.user.username) }}
        <small>{{ session.account_type === 'company' ? 'Firma' : 'Twórca' }}</small>
      </span>
      <button 
        :class="{ active: currentTab === 'list' }" 
        @click="currentTab = 'list'"
      >
        📋 Lista Kampanii
      </button>
      <button 
        :class="{ active: currentTab === 'create' }" 
        @click="currentTab = 'create'"
      >
        ➕ Nowa Kampania
      </button>
      <button 
        :class="{ active: currentTab === 'edit' }" 
        @click="currentTab = 'edit'"
      >
        ✏️ Edycja Kampanii
      </button>
      <button 
        :class="{ active: currentTab === 'test-data' }" 
        @click="currentTab = 'test-data'"
      >
        ⚙️ Dane Testowe
      </button>
      <button class="logout-button" @click="logout">Wyloguj</button>
    </nav>

    <main>
      <!-- Dzięki v-if komponenty są odmontowywane i zamontowywane ponownie, 
           co wymusza wykonanie onMounted i pobranie aktualnych danych z bazy -->
      <CampaignList 
        v-if="currentTab === 'list'" 
        @edit-campaign="handleEditCampaign"
        @view-campaign="handleViewCampaign"
        @create-new="currentTab = 'create'"
      />

      <CampaignDetails
        v-else-if="currentTab === 'details'"
        :campaign-id="detailsCampaignId"
        :session="session"
        @back="currentTab = 'list'"
        @edit-campaign="handleDetailsEdit"
      />

      <CreateCampaign 
        v-else-if="currentTab === 'create'" 
        @campaign-created="handleCampaignCreated"
      />

      <div v-else-if="currentTab === 'edit'" class="edit-wrapper">
        <div class="selector-bar">
          <label>Wybrane ID kampanii: </label>
          <input type="number" v-model.number="editCampaignId" min="1" />
        </div>
        <EditCampaign :campaign-id="editCampaignId" />
      </div>

      <TestSeeder v-else-if="currentTab === 'test-data'" />
    </main>
  </div>
</template>

