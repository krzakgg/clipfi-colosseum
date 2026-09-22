<script setup>
import { ref } from 'vue'
import CampaignList from './views/Campaign/CampaignList.vue'
import CreateCampaign from './views/Campaign/CreateCampaign.vue'
import EditCampaign from './views/Campaign/EditCampaign.vue'
import TestSeeder from './views/Campaign/TestSeeder.vue'

const currentTab = ref('list') // Ustawiamy widok listy jako domyślny
const editCampaignId = ref(null)

// Reakcja na kliknięcie "Edytuj" w tabeli
const handleEditCampaign = (id) => {
  editCampaignId.value = id
  currentTab.value = 'edit'
}

// Przejście do widoku listy po pomyślnym dodaniu kampanii
const handleCampaignCreated = () => {
  currentTab.value = 'list'
}
</script>

<template>
  <div class="app-layout">
    <nav class="nav-bar">
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
    </nav>

    <main>
      <!-- Dzięki v-if komponenty są odmontowywane i zamontowywane ponownie, 
           co wymusza wykonanie onMounted i pobranie aktualnych danych z bazy -->
      <CampaignList 
        v-if="currentTab === 'list'" 
        @edit-campaign="handleEditCampaign"
        @create-new="currentTab = 'create'"
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

<style scoped>
.app-layout { font-family: system-ui, sans-serif; background: #f7fafc; min-height: 100vh; }
.nav-bar {
  display: flex;
  gap: 0.75rem;
  justify-content: center;
  padding: 1rem;
  background: #ffffff;
  border-bottom: 1px solid #e2e8f0;
}
.nav-bar button {
  padding: 0.5rem 1rem;
  border: 1px solid #cbd5e0;
  background: white;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 500;
}
.nav-bar button.active {
  background: #3182ce;
  color: white;
  border-color: #3182ce;
}
.selector-bar {
  max-width: 800px;
  margin: 1rem auto 0;
  text-align: center;
  font-size: 0.9rem;
}
.selector-bar input {
  padding: 0.4rem;
  width: 80px;
  margin-left: 0.5rem;
}
</style>