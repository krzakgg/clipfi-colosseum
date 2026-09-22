<script setup>
import { ref, watch, onMounted } from 'vue'

const props = defineProps({
  campaignId: { type: Number, default: 1 }
})

const applications = ref([])
const loading = ref(false)
const feedbackTexts = ref({}) // Słownik przechowujący wpisane uwagi per ID zgłoszenia

const fetchApplications = async () => {
  if (!props.campaignId) return
  loading.value = true
  try {
    const res = await fetch(`http://localhost:8000/api/applications/campaign/${props.campaignId}`)
    if (res.ok) {
      applications.value = await res.json()
    }
  } catch (err) {
    console.error('Błąd pobierania zgłoszeń:', err)
  } finally {
    loading.value = false
  }
}

const updateStatus = async (appId, newStatus) => {
  const feedback = feedbackTexts.value[appId] || null

  try {
    const res = await fetch(`http://localhost:8000/api/applications/${appId}/status`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        status: newStatus,
        feedback: feedback
      })
    })

    if (!res.ok) throw new Error('Błąd zmiany statusu')

    const updatedApp = await res.json()
    // Aktualizujemy obiekt lokalnie w tablicy
    const index = applications.value.findIndex(a => a.id === appId)
    if (index !== -1) {
      applications.value[index] = updatedApp
    }
  } catch (err) {
    alert(err.message)
  }
}

watch(() => props.campaignId, fetchApplications)
onMounted(fetchApplications)
</script>

<template>
  <div class="manage-box">
    <h2>Zgłoszenia do Kampanii (ID: {{ campaignId }})</h2>

    <div v-if="loading">Wczytywanie zgłoszeń...</div>

    <div v-else-if="applications.length === 0" class="empty">
      Brak zgłoszeń od twórców dla tej kampanii.
    </div>

    <div v-else class="apps-list">
      <div v-for="app in applications" :key="app.id" class="app-card">
        <div class="card-header">
          <span><strong>Twórca ID:</strong> #{{ app.creator_id }}</span>
          <span :class="['status-badge', app.status]">
            {{ app.status }}
          </span>
        </div>

        <div class="card-body">
          <p><strong>Typ treści:</strong> {{ app.proposed_content_type || 'Brak' }}</p>
          <p><strong>Proponowana stawka:</strong> {{ app.proposed_rate ? `${app.proposed_rate} PLN` : 'Domyślna' }}</p>
          <p><strong>Pitch / Pomysł:</strong></p>
          <blockquote class="pitch-text">{{ app.pitch || 'Brak opisu pomysłu' }}</blockquote>

          <div v-if="app.feedback" class="feedback-info">
            <strong>Uwagi marki:</strong> {{ app.feedback }}
          </div>
        </div>

        <!-- Panel akcji dla zgłoszeń oczekujących -->
        <div v-if="app.status === 'pending'" class="card-actions">
          <input 
            v-model="feedbackTexts[app.id]" 
            type="text" 
            placeholder="Opcjonalna uwaga / powód decyzji..."
            class="feedback-input"
          />
          <div class="btn-group">
            <button @click="updateStatus(app.id, 'accepted')" class="btn btn-accept">
              ✅ Zaakceptuj
            </button>
            <button @click="updateStatus(app.id, 'rejected')" class="btn btn-reject">
              ❌ Odrzuć
            </button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.manage-box {
  max-width: 800px;
  margin: 2rem auto;
  padding: 1.5rem;
  background: #ffffff;
  border-radius: 8px;
  font-family: system-ui, sans-serif;
}
.apps-list { display: flex; flex-direction: column; gap: 1rem; margin-top: 1rem; }
.app-card {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 1rem;
  background: #f7fafc;
}
.card-header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #edf2f7; padding-bottom: 0.5rem; }
.status-badge {
  padding: 0.2rem 0.6rem;
  border-radius: 9999px;
  font-size: 0.75rem;
  font-weight: bold;
  text-transform: uppercase;
}
.status-badge.pending { background: #feebc8; color: #744210; }
.status-badge.accepted { background: #c6f6d5; color: #22543d; }
.status-badge.rejected { background: #fed7d7; color: #742a2a; }

.pitch-text {
  margin: 0.5rem 0;
  padding: 0.5rem;
  background: #ffffff;
  border-left: 3px solid #3182ce;
  font-style: italic;
  font-size: 0.9rem;
}
.card-actions { margin-top: 1rem; display: flex; flex-direction: column; gap: 0.5rem; }
.feedback-input { padding: 0.4rem; border: 1px solid #cbd5e0; border-radius: 4px; }
.btn-group { display: flex; gap: 0.5rem; }
.btn { flex: 1; padding: 0.5rem; border: none; border-radius: 4px; font-weight: bold; cursor: pointer; color: white; }
.btn-accept { background: #38a169; }
.btn-reject { background: #e53e3e; }
.empty { text-align: center; color: #718096; padding: 2rem; }
</style>