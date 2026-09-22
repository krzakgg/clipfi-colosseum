<script setup>
import { ref, onMounted } from 'vue'

const emit = defineEmits(['edit-campaign', 'create-new'])

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

<style scoped>
.list-container {
  max-width: 1000px;
  margin: 2rem auto;
  padding: 1.5rem;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05);
  font-family: system-ui, sans-serif;
}
.header-actions {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 1.5rem;
}
.btn-refresh {
  padding: 0.4rem 0.8rem;
  background: #edf2f7;
  border: 1px solid #cbd5e0;
  border-radius: 6px;
  cursor: pointer;
}
.table-wrapper {
  overflow-x: auto;
}
.campaigns-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}
.campaigns-table th, .campaigns-table td {
  padding: 0.75rem 1rem;
  border-bottom: 1px solid #e2e8f0;
  font-size: 0.9rem;
}
.campaigns-table th {
  background: #f7fafc;
  color: #4a5568;
  font-weight: 600;
}
.title-cell { font-weight: 600; color: #2d3748; }
.actions-cell { display: flex; gap: 0.5rem; }

.btn-action {
  padding: 0.35rem 0.7rem;
  border: none;
  border-radius: 4px;
  font-size: 0.8rem;
  font-weight: 600;
  cursor: pointer;
}
.btn-edit { background: #ebf8ff; color: #2b6cb0; }
.btn-edit:hover { background: #bee3f8; }
.btn-delete { background: #fff5f5; color: #c53030; }
.btn-delete:hover { background: #fed7d7; }

.badge {
  padding: 0.2rem 0.5rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: 600;
}
.badge-public { background: #e6fffa; color: #234e52; }
.badge-private { background: #feebc8; color: #744210; }

.empty-state, .state-msg { text-align: center; padding: 2rem; color: #718096; }
.btn-link { color: #3182ce; background: none; border: none; cursor: pointer; text-decoration: underline; font-weight: 600; }
.alert-danger { padding: 0.75rem; background: #fed7d7; color: #742a2a; border-radius: 6px; }
</style>