<script setup>
import { ref, watch, onMounted } from 'vue'

const props = defineProps({
  campaignId: { type: Number, required: true },
  companyId: { type: Number, required: true }
})

const applications = ref([])
const submissions = ref([])
const loading = ref(false)
const submissionsLoading = ref(false)
const feedbackTexts = ref({}) // Słownik przechowujący wpisane uwagi per ID zgłoszenia
const submissionFeedback = ref({})
const refLinkUrls = ref({})
const generatedRefLinks = ref({})
const refLinkClicks = ref({})
const refLinkLoading = ref({})
const refLinkErrors = ref({})

const fetchApplications = async () => {
  if (!props.campaignId) return
  loading.value = true
  try {
    const res = await fetch(`http://localhost:8000/api/applications/campaign/${props.campaignId}?company_id=${props.companyId}`)
    if (res.ok) {
      applications.value = await res.json()
      await fetchRefLinks()
      await fetchSubmissions()
    }
  } catch (err) {
    console.error('Błąd pobierania zgłoszeń:', err)
  } finally {
    loading.value = false
  }
}

const fetchSubmissions = async () => {
  submissionsLoading.value = true
  try {
    const res = await fetch(`http://localhost:8000/api/submissions/campaign/${props.campaignId}?company_id=${props.companyId}`)
    if (res.ok) submissions.value = await res.json()
  } finally {
    submissionsLoading.value = false
  }
}

const reviewSubmission = async (submissionId, newStatus) => {
  try {
    const res = await fetch(`http://localhost:8000/api/submissions/${submissionId}/review`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        company_id: props.companyId,
        status: newStatus,
        feedback: submissionFeedback.value[submissionId] || null
      })
    })
    const data = await res.json()
    if (!res.ok) throw new Error(data.detail || 'Błąd zmiany statusu materiału')
    const index = submissions.value.findIndex(submission => submission.id === submissionId)
    if (index !== -1) submissions.value[index] = data
  } catch (error) {
    alert(error.message)
  }
}

const fetchRefLinks = async () => {
  const res = await fetch(`http://localhost:8000/api/reflinks/campaign/${props.campaignId}?company_id=${props.companyId}`)
  if (!res.ok) return

  const links = await res.json()
  for (const link of links) {
    const application = applications.value.find(app => app.creator_id === link.creator_id)
    if (!application || generatedRefLinks.value[application.id]) continue

    generatedRefLinks.value[application.id] = `http://localhost:8000/r/${link.code}`
    refLinkUrls.value[application.id] = link.url
    refLinkClicks.value[application.id] = link.clicks_count
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
        feedback: feedback,
        company_id: props.companyId
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

const createRefLink = async (application) => {
  const appId = application.id
  refLinkLoading.value[appId] = true
  refLinkErrors.value[appId] = ''
  generatedRefLinks.value[appId] = ''
  refLinkClicks.value[appId] = 0

  try {
    const res = await fetch('http://localhost:8000/api/reflinks', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        campaign_id: props.campaignId,
        creator_id: application.creator_id,
        company_id: props.companyId,
        url: refLinkUrls.value[appId]
      })
    })
    const data = await res.json()
    if (!res.ok) {
      const detail = Array.isArray(data.detail)
        ? data.detail.map(item => item.msg).join('; ')
        : data.detail
      throw new Error(detail || 'Nie udało się wygenerować reflinka')
    }
    generatedRefLinks.value[appId] = `http://localhost:8000/r/${data.code}`
    refLinkClicks.value[appId] = data.clicks_count
  } catch (err) {
    refLinkErrors.value[appId] = err.message
  } finally {
    refLinkLoading.value[appId] = false
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

        <div v-if="app.status === 'accepted'" class="ref-link-actions">
          <strong>Reflink dla twórcy</strong>
          <div class="ref-link-inline-form">
            
            <input
              v-model="refLinkUrls[app.id]"
              type="url"
              placeholder="https://adres-docelowy.pl"
            />
            <button
              class="btn btn-accept"
              :disabled="refLinkLoading[app.id] || !refLinkUrls[app.id]"
              @click="createRefLink(app)"
            >
              {{ refLinkLoading[app.id] ? 'Generowanie...' : 'Wygeneruj reflink' }}
            </button>
          </div>
          <div v-if="refLinkErrors[app.id]" class="alert alert-danger">{{ refLinkErrors[app.id] }}</div>
          <input
            v-if="generatedRefLinks[app.id]"
            :value="generatedRefLinks[app.id]"
            class="generated-ref-link"
            readonly
            @focus="$event.target.select()"
          />
          <span v-if="generatedRefLinks[app.id]" class="ref-link-clicks">
            Kliknięcia: {{ refLinkClicks[app.id] ?? 0 }}
          </span>
        </div>
      </div>
    </div>

    <section class="submissions-section">
      <h2>Materiały do akceptacji</h2>
      <div v-if="submissionsLoading">Wczytywanie materiałów...</div>
      <div v-else-if="submissions.length === 0" class="empty">Brak wysłanych materiałów.</div>
      <div v-else class="apps-list">
        <div v-for="submission in submissions" :key="submission.id" class="app-card">
          <div class="card-header">
            <span><strong>Twórca ID:</strong> #{{ submission.creator_id }}</span>
            <span :class="['status-badge', submission.status]">{{ submission.status }}</span>
          </div>
          <p><strong>Materiał:</strong> <a :href="submission.video_url" target="_blank" rel="noreferrer">Otwórz w {{ submission.platform }}</a></p>
          <p><strong>Typ:</strong> {{ submission.content_type }}</p>
          <p v-if="submission.feedback"><strong>Uwagi:</strong> {{ submission.feedback }}</p>
          <div v-if="submission.status !== 'approved'" class="card-actions">
            <input v-model="submissionFeedback[submission.id]" class="feedback-input" placeholder="Uwagi dla twórcy..." />
            <div class="btn-group">
              <button class="btn btn-accept" @click="reviewSubmission(submission.id, 'approved')">Zaakceptuj materiał</button>
              <button class="btn btn-reject" @click="reviewSubmission(submission.id, 'revision_requested')">Poproś o poprawki</button>
              <button class="btn btn-reject" @click="reviewSubmission(submission.id, 'rejected')">Odrzuć</button>
            </div>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

