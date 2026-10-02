<script setup>
import { ref, computed, watch, onMounted } from 'vue'

const props = defineProps({
  campaignId: { type: Number, required: true },
  companyId: { type: Number, required: true },
  section: { type: String, default: 'all' }
})

const applications = ref([])
const submissions = ref([])
const loading = ref(false)
const submissionsLoading = ref(false)
const submissionView = ref('list')
const selectedSubmissionId = ref(null)
const feedbackTexts = ref({}) // Feedback keyed by application ID
const submissionFeedback = ref({})
const refLinkUrls = ref({})
const generatedRefLinks = ref({})
const refLinkClicks = ref({})
const refLinkPayouts = ref({})
const refLinkLoading = ref({})
const refLinkErrors = ref({})

const creatorName = (item) => item.creator_full_name || item.creator_username || `Creator #${item.creator_id}`
const creatorHandle = (item) => item.creator_username ? `@${item.creator_username}` : `ID ${item.creator_id}`
const creatorLanguages = (item) => item.creator_languages?.join(', ') || '—'
const creatorSocials = (item) => Object.keys(item.creator_platform_stats || {}).slice(0, 4)
const formatDate = (date) => date ? new Date(date).toLocaleDateString('en-US') : '—'
const statusLabel = (status) => ({ pending: 'Pending', accepted: 'Accepted', rejected: 'Rejected', approved: 'Approved', revision_requested: 'Revision requested' }[status] || status)
const selectedSubmission = computed(() => submissions.value.find(submission => submission.id === selectedSubmissionId.value))

const openSubmissionReview = (submission) => {
  selectedSubmissionId.value = submission.id
  submissionView.value = 'review'
}

const closeSubmissionReview = () => {
  selectedSubmissionId.value = null
  submissionView.value = 'list'
}

const fetchApplications = async () => {
  if (!props.campaignId) return
  loading.value = true
  try {
    const res = await fetch(`http://localhost:8000/api/applications/campaign/${props.campaignId}?company_id=${props.companyId}`)
    if (res.ok) {
      applications.value = await res.json()
      await fetchRefLinks()
      if (props.section !== 'creators') await fetchSubmissions()
    }
  } catch (err) {
    console.error('Could not load applications:', err)
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
    if (!res.ok) throw new Error(data.detail || 'Could not update material status')
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

    generatedRefLinks.value[application.id] = link.public_url
    refLinkUrls.value[application.id] = link.url
    refLinkClicks.value[application.id] = link.clicks_count
    refLinkPayouts.value[application.id] = link.click_payout
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

    if (!res.ok) throw new Error('Could not update application status')

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
      throw new Error(detail || 'Could not generate referral link')
    }
    generatedRefLinks.value[appId] = data.public_url
    refLinkClicks.value[appId] = data.clicks_count
    refLinkPayouts.value[appId] = data.click_payout
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
    <div v-if="props.section !== 'submissions'" class="manage-heading">
      <div><span class="manage-eyebrow">Campaign workspace</span><h2>Creators and applications</h2></div>
      <span class="manage-count">{{ applications.length }} applications</span>
    </div>

    <div v-if="props.section !== 'submissions' && loading">Loading applications...</div>

    <div v-else-if="props.section !== 'submissions' && applications.length === 0" class="empty">
      No creator applications for this campaign.
    </div>

    <div v-else-if="props.section !== 'submissions'" class="creator-table">
      <div class="creator-table-head">
        <span>Creator</span><span>Language</span><span>Socials</span><span>Views</span><span>Earned</span><span>Join date</span><span>Status</span>
      </div>
      <div v-for="app in applications" :key="app.id" class="creator-table-row">
        <div class="creator-identity">
          <img v-if="app.creator_avatar_url" :src="app.creator_avatar_url" :alt="creatorName(app)" />
          <span v-else class="creator-avatar">{{ creatorName(app).charAt(0).toUpperCase() }}</span>
          <span><strong>{{ creatorName(app) }}</strong><small>{{ creatorHandle(app) }}</small></span>
        </div>
        <span class="creator-language">{{ creatorLanguages(app) }}</span>
        <span class="creator-socials">
          <i v-for="social in creatorSocials(app)" :key="social" :title="social">{{ social.slice(0, 1).toUpperCase() }}</i>
          <em v-if="!creatorSocials(app).length">—</em>
        </span>
        <span class="creator-table-value">—</span>
        <span class="creator-table-value">{{ app.proposed_rate ? `${app.proposed_rate} PLN` : '—' }}</span>
        <span class="creator-table-value">{{ formatDate(app.created_at) }}</span>
        <span :class="['status-badge', app.status]">{{ statusLabel(app.status) }}</span>

        <div class="creator-row-details">
          <div class="creator-facts">
            <span><small>Content type</small><strong>{{ app.proposed_content_type || 'Not specified' }}</strong></span>
            <span><small>Rate</small><strong>{{ app.proposed_rate ? `${app.proposed_rate} PLN` : 'Default' }}</strong></span>
            <span><small>Applied</small><strong>{{ formatDate(app.created_at) }}</strong></span>
          </div>
          <p class="pitch-label">Creator pitch</p>
          <blockquote class="pitch-text">{{ app.pitch || 'The creator did not add a pitch.' }}</blockquote>
          <div v-if="app.feedback" class="feedback-info"><strong>Company feedback:</strong> {{ app.feedback }}</div>
          <div v-if="app.status === 'pending'" class="card-actions">
            <input v-model="feedbackTexts[app.id]" type="text" placeholder="Optional feedback or reason..." class="feedback-input" />
            <div class="btn-group"><button @click="updateStatus(app.id, 'accepted')" class="btn btn-accept">✅ Accept</button><button @click="updateStatus(app.id, 'rejected')" class="btn btn-reject">❌ Reject</button></div>
          </div>
          <div v-if="app.status === 'accepted'" class="ref-link-actions">
            <strong>Creator referral link</strong>
            <div v-if="!generatedRefLinks[app.id]" class="ref-link-inline-form"><input v-model="refLinkUrls[app.id]" type="url" placeholder="https://destination-url.com" /><button class="btn btn-accept" :disabled="refLinkLoading[app.id] || !refLinkUrls[app.id]" @click="createRefLink(app)">{{ refLinkLoading[app.id] ? 'Generating...' : 'Generate referral link' }}</button></div>
            <div v-if="refLinkErrors[app.id]" class="alert alert-danger">{{ refLinkErrors[app.id] }}</div>
            <input v-if="generatedRefLinks[app.id]" :value="generatedRefLinks[app.id]" class="generated-ref-link" readonly @focus="$event.target.select()" />
            <span v-if="generatedRefLinks[app.id]" class="ref-link-clicks">Unique clicks: {{ refLinkClicks[app.id] ?? '—' }}<template v-if="refLinkPayouts[app.id] != null"> · payout: {{ refLinkPayouts[app.id] }} PLN</template></span>
          </div>
        </div>
      </div>
    </div>
    <!-- Legacy card content intentionally replaced by the compact creator table above. -->
    <div v-if="false" class="apps-list creator-list">
      <div v-for="app in applications" :key="app.id" class="app-card">
        <div class="card-header">
          <div class="creator-identity">
            <img v-if="app.creator_avatar_url" :src="app.creator_avatar_url" :alt="creatorName(app)" />
            <span v-else class="creator-avatar">{{ creatorName(app).charAt(0).toUpperCase() }}</span>
            <span><strong>{{ creatorName(app) }}</strong><small>{{ creatorHandle(app) }}</small></span>
          </div>
          <span :class="['status-badge', app.status]">{{ statusLabel(app.status) }}</span>
        </div>

        <div class="card-body">
          <div class="creator-facts">
            <span><small>Content type</small><strong>{{ app.proposed_content_type || 'Not specified' }}</strong></span>
            <span><small>Rate</small><strong>{{ app.proposed_rate ? `${app.proposed_rate} PLN` : 'Default' }}</strong></span>
            <span><small>Applied</small><strong>{{ formatDate(app.created_at) }}</strong></span>
          </div>
          <p class="pitch-label">Creator pitch</p>
          <blockquote class="pitch-text">{{ app.pitch || 'The creator did not add a pitch.' }}</blockquote>

          <div v-if="app.feedback" class="feedback-info">
            <strong>Company feedback:</strong> {{ app.feedback }}
          </div>
        </div>

        <!-- Actions for pending applications -->
        <div v-if="app.status === 'pending'" class="card-actions">
          <input 
            v-model="feedbackTexts[app.id]" 
            type="text" 
            placeholder="Optional feedback or reason..."
            class="feedback-input"
          />
          <div class="btn-group">
            <button @click="updateStatus(app.id, 'accepted')" class="btn btn-accept">
              ✅ Accept
            </button>
            <button @click="updateStatus(app.id, 'rejected')" class="btn btn-reject">
              ❌ Reject
            </button>
          </div>
        </div>

        <div v-if="app.status === 'accepted'" class="ref-link-actions">
          <strong>Creator referral link</strong>
          <div v-if="!generatedRefLinks[app.id]" class="ref-link-inline-form">
            
            <input
              v-model="refLinkUrls[app.id]"
              type="url"
              placeholder="https://destination-url.com"
            />
            <button
              class="btn btn-accept"
              :disabled="refLinkLoading[app.id] || !refLinkUrls[app.id]"
              @click="createRefLink(app)"
            >
              {{ refLinkLoading[app.id] ? 'Generating...' : 'Generate referral link' }}
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
            Unique clicks: {{ refLinkClicks[app.id] ?? '—' }}
            <template v-if="refLinkPayouts[app.id] != null"> · payout: {{ refLinkPayouts[app.id] }} PLN</template>
          </span>
        </div>
      </div>
    </div>

    <section v-if="props.section !== 'creators'" class="submissions-section">
      <template v-if="submissionView === 'list'">
        <div class="manage-heading submissions-heading"><div><span class="manage-eyebrow">Submission library</span><h2>Creator videos</h2><p class="submissions-intro">Choose a submission to inspect and evaluate it.</p></div><span class="manage-count">{{ submissions.length }} materials</span></div>
        <div v-if="submissionsLoading" class="submission-state">Loading materials...</div>
        <div v-else-if="submissions.length === 0" class="submission-state">No submitted materials.</div>
        <div v-else class="submission-list">
          <article v-for="submission in submissions" :key="submission.id" class="submission-list-item">
            <div class="submission-list-identity">
              <div class="creator-identity">
                <img v-if="submission.creator_avatar_url" :src="submission.creator_avatar_url" :alt="creatorName(submission)" />
                <span v-else class="creator-avatar">{{ creatorName(submission).charAt(0).toUpperCase() }}</span>
                <span><strong>{{ creatorName(submission) }}</strong><small>{{ creatorHandle(submission) }}</small></span>
              </div>
              <span :class="['status-badge', submission.status]">{{ statusLabel(submission.status) }}</span>
            </div>
            <div class="submission-list-meta"><span>{{ submission.platform }}</span><span>{{ submission.content_type }}</span><span>{{ submission.views_count || 0 }} views</span><span>{{ formatDate(submission.created_at) }}</span></div>
            <div class="submission-list-actions">
              <a class="submission-link" :href="submission.video_url" target="_blank" rel="noreferrer">Open video <span>↗</span></a>
              <button class="submission-review-button" @click="openSubmissionReview(submission)">Review submission <span>→</span></button>
            </div>
          </article>
        </div>
      </template>

      <template v-else-if="selectedSubmission">
        <div class="submission-review-heading">
          <button class="submission-back-button" @click="closeSubmissionReview">← Back to submissions</button>
          <span class="manage-eyebrow">Submission review</span>
          <h2>{{ creatorName(selectedSubmission) }} · {{ selectedSubmission.content_type }}</h2>
          <p>Review this creator video and choose the next status.</p>
        </div>
        <article class="submission-review-card">
          <div class="submission-review-topline">
            <div><strong>{{ creatorName(selectedSubmission) }}</strong><small>{{ creatorHandle(selectedSubmission) }}</small></div>
            <span :class="['status-badge', selectedSubmission.status]">{{ statusLabel(selectedSubmission.status) }}</span>
          </div>
          <div class="submission-facts"><span><small>Platform</small><strong>{{ selectedSubmission.platform }}</strong></span><span><small>Type</small><strong>{{ selectedSubmission.content_type }}</strong></span><span><small>Views</small><strong>{{ selectedSubmission.views_count || 0 }}</strong></span><span><small>Submitted</small><strong>{{ formatDate(selectedSubmission.created_at) }}</strong></span></div>
          <a class="submission-video-link" :href="selectedSubmission.video_url" target="_blank" rel="noreferrer">Open submitted video <span>↗</span></a>
          <p v-if="selectedSubmission.feedback" class="submission-feedback"><strong>Previous feedback:</strong> {{ selectedSubmission.feedback }}</p>
          <div v-if="selectedSubmission.status !== 'approved'" class="submission-review-actions">
            <label for="submission-feedback">Feedback for creator</label>
            <textarea id="submission-feedback" v-model="submissionFeedback[selectedSubmission.id]" rows="4" placeholder="Write feedback or explain the decision..."></textarea>
            <div class="btn-group">
              <button class="btn btn-accept" @click="reviewSubmission(selectedSubmission.id, 'approved')">Approve video</button>
              <button class="btn btn-revision" @click="reviewSubmission(selectedSubmission.id, 'revision_requested')">Request revision</button>
              <button class="btn btn-reject" @click="reviewSubmission(selectedSubmission.id, 'rejected')">Reject video</button>
            </div>
          </div>
          <div v-else class="submission-approved-note">This submission has already been approved.</div>
        </article>
      </template>
    </section>
  </div>
</template>

