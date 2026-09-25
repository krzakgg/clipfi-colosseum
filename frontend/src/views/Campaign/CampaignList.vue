<script setup>
import { ref, onMounted } from 'vue'

const emit = defineEmits(['edit-campaign', 'view-campaign', 'create-new'])

const campaigns = ref([])
const loading = ref(false)
const error = ref('')

// Pobranie listy kampanii z API
const fetchCampaigns = async () => {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch('http://localhost:8000/api/campaigns')
    if (!res.ok) throw new Error('Nie udało się pobrać listy kampanii')
    campaigns.value = await res.json()
  } catch (err) {
    error.value = err.message
  } finally {
    loading.value = false
  }
}

// Usunięcie kampanii
const handleDelete = async (id, title) => {
  if (!confirm(`Czy na pewno chcesz usunąć kampanię "${title}" (ID: ${id})?`)) return

  try {
    const res = await fetch(`http://localhost:8000/api/campaigns/${id}`, {
      method: 'DELETE'
    })
    if (!res.ok) throw new Error('Błąd podczas usuwania kampanii')

    // Usuwamy kampanię z lokalnej tablicy, aby nie przeładowywać całej strony
    campaigns.value = campaigns.value.filter(c => c.id !== id)
  } catch (err) {
    alert(err.message)
  }
}

// Przejście do widoku edycji
const handleEdit = (id) => {
  emit('edit-campaign', id)
}

const handleView = (id) => {
  emit('view-campaign', id)
}

onMounted(fetchCampaigns)
</script>

<template>
  <div class="list-container">
    <div class="header-actions">
      <h2>Lista Kampanii</h2>
      <button @click="fetchCampaigns" class="btn-refresh">🔄 Odśwież</button>
    </div>

    <div v-if="loading" class="state-msg">Wczytywanie kampanii...</div>
    <div v-else-if="error" class="alert alert-danger">{{ error }}</div>

    <div v-else-if="campaigns.length === 0" class="empty-state">
      Brak kampanii w bazie danych. 
      <button @click="$emit('create-new')" class="btn-link">Dodaj pierwszą kampanię</button>
    </div>

    <div v-else class="table-wrapper">
      <table class="campaigns-table">
        <thead>
          <tr>
            <th>ID</th>
            <th>Tytuł</th>
            <th>Firma ID</th>
            <th>Budżet całkowity</th>
            <th>Budżet / Twórcę</th>
            <th>Prywatna</th>
            <th>Akcje</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="c in campaigns" :key="c.id">
            <td><strong>#{{ c.id }}</strong></td>
            <td class="title-cell">{{ c.title }}</td>
            <td>{{ c.company_id }}</td>
            <td>{{ c.total_budget ? `${c.total_budget} PLN` : '-' }}</td>
            <td>{{ c.budget_per_creator ? `${c.budget_per_creator} PLN` : '-' }}</td>
            <td>
              <span :class="['badge', c.is_private ? 'badge-private' : 'badge-public']">
                {{ c.is_private ? 'Prywatna' : 'Publiczna' }}
              </span>
            </td>
            <td class="actions-cell">
              <button @click="handleView(c.id)" class="btn-action btn-view">
                👁️ Szczegóły
              </button>
              <button @click="handleEdit(c.id)" class="btn-action btn-edit">
                ✏️ Edytuj
              </button>
              <button @click="handleDelete(c.id, c.title)" class="btn-action btn-delete">
                🗑️ Usuń
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

