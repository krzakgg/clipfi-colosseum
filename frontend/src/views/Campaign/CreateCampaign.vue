<script setup>
import { ref, reactive, onMounted } from 'vue'

const emit = defineEmits(['campaign-created'])

const loading = ref(false)
const successMessage = ref('')
const errorMessage = ref('')
const companies = ref([])

// Pobieranie listy firm z backendu
const fetchCompanies = async () => {
  try {
    const res = await fetch('http://localhost:8000/api/companies')
    if (res.ok) {
      companies.value = await res.json()
    } else {
      console.error('Nie udało się pobrać listy firm.')
    }
  } catch (err) {
    console.error('Błąd połączenia z serwerem:', err)
  }
}

onMounted(fetchCompanies)

// Reaktywny stan formularza
const form = reactive({
  company_id: '',
  title: '',
  description: '',
  is_private: false,

  // Opis i materiały
  product_description: '',
  press_kit_url: '',
  brand_guidelines: '',

  // Budżet
  total_budget: null,
  budget_per_creator: null,

  // Wymagania i zasady
  languages_str: 'PL, EN',
  min_views: 0,
  min_subscribers: 0,
  max_videos_per_creator: 1,

  // Stawki i rozliczenie
  short_payout: null,
  long_payout: null,
  payout_per_views: null,
  payout_per_click: null
})

const handleSubmit = async () => {
  loading.value = true
  successMessage.value = ''
  errorMessage.value = ''

  const payload = {
    company_id: parseInt(form.company_id),
    title: form.title,
    description: form.description || null,
    is_private: form.is_private,

    product_description: form.product_description || null,
    press_kit_url: form.press_kit_url || null,
    brand_guidelines: form.brand_guidelines || null,

    total_budget: parseFloat(form.total_budget),
    budget_per_creator: form.budget_per_creator ? parseFloat(form.budget_per_creator) : null,

    languages: form.languages_str.split(',').map(l => l.trim().toUpperCase()).filter(Boolean),
    min_views: parseInt(form.min_views) || 0,
    min_subscribers: parseInt(form.min_subscribers) || 0,
    max_videos_per_creator: form.max_videos_per_creator ? parseInt(form.max_videos_per_creator) : null,

    payout_by_content_type: {
      Short: form.short_payout ? parseFloat(form.short_payout) : 0,
      LongVideo: form.long_payout ? parseFloat(form.long_payout) : 0
    },
    payout_per_views: form.payout_per_views ? parseFloat(form.payout_per_views) : null,
    payout_per_click: form.payout_per_click ? parseFloat(form.payout_per_click) : null
  }

  try {
    const response = await fetch('http://localhost:8000/api/campaigns', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    const data = await response.json()

    if (!response.ok) {
      throw new Error(data.detail || 'Błąd podczas tworzenia kampanii')
    }

    successMessage.value = `Kampania "${data.title}" została pomyślnie utworzona!`
    
    // Reset stanu formularza
    Object.assign(form, {
      company_id: '',
      title: '',
      description: '',
      is_private: false,
      product_description: '',
      press_kit_url: '',
      brand_guidelines: '',
      total_budget: null,
      budget_per_creator: null,
      languages_str: 'PL, EN',
      min_views: 0,
      min_subscribers: 0,
      max_videos_per_creator: 1,
      short_payout: null,
      long_payout: null,
      payout_per_views: null,
      payout_per_click: null
    })

    // Emitowanie zdarzenia do rodzica (np. App.vue)
    emit('campaign-created', data)
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="campaign-container">
    <h2>Stwórz nową kampanię</h2>

    <div v-if="successMessage" class="alert alert-success">{{ successMessage }}</div>
    <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

    <form @submit.prevent="handleSubmit" class="campaign-form">
      
      <!-- Sekcja 1: Podstawowe informacje -->
      <fieldset>
        <legend>1. Podstawowe informacje</legend>
        
        <div class="form-group">
          <label>Wybierz firmę *</label>
          <select v-model="form.company_id" required>
            <option value="" disabled>-- Wybierz firmę z listy --</option>
            <option v-for="company in companies" :key="company.id" :value="company.id">
              {{ company.name }} (ID: {{ company.id }})
            </option>
          </select>
        </div>

        <div class="form-group">
          <label>Tytuł kampanii *</label>
          <input v-model="form.title" type="text" placeholder="np. Letnia promocja aplikacji" required />
        </div>

        <div class="form-group">
          <label>Opis ogólny</label>
          <textarea v-model="form.description" rows="3" placeholder="Krótki opis celu kampanii..."></textarea>
        </div>

        <div class="form-group checkbox-group">
          <label>
            <input type="checkbox" v-model="form.is_private" />
            Kampania prywatna (tylko dla zaproszonych twórców)
          </label>
        </div>
      </fieldset>

      <!-- Sekcja 2: Materiały i Opis Produktu -->
      <fieldset>
        <legend>2. Materiały dla twórców</legend>

        <div class="form-group">
          <label>Szczegółowy opis produktu</label>
          <textarea v-model="form.product_description" rows="3" placeholder="Opisz kluczowe funkcje produktu..."></textarea>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Link do Press Kit (URL)</label>
            <input v-model="form.press_kit_url" type="url" placeholder="https://..." />
          </div>

          <div class="form-group">
            <label>Wytyczne marki (Brand Guidelines)</label>
            <input v-model="form.brand_guidelines" type="text" placeholder="np. Zasady użycia logo, kolory..." />
          </div>
        </div>
      </fieldset>

      <!-- Sekcja 3: Budżet i Wymagania -->
      <fieldset>
        <legend>3. Budżet i Wymagania</legend>

        <div class="grid-2">
          <div class="form-group">
            <label>Całkowity budżet (PLN) *</label>
            <input v-model="form.total_budget" type="number" step="0.01" min="0" placeholder="10000.00" required />
          </div>

          <div class="form-group">
            <label>Budżet na 1 twórcę (PLN)</label>
            <input v-model="form.budget_per_creator" type="number" step="0.01" min="0" placeholder="1500.00" />
          </div>
        </div>

        <div class="grid-3">
          <div class="form-group">
            <label>Języki (oddzielone przecinkami)</label>
            <input v-model="form.languages_str" type="text" placeholder="PL, EN" />
          </div>

          <div class="form-group">
            <label>Min. wyświetleń</label>
            <input v-model="form.min_views" type="number" min="0" placeholder="1000" />
          </div>

          <div class="form-group">
            <label>Min. subskrypcji/obserwujących</label>
            <input v-model="form.min_subscribers" type="number" min="0" placeholder="5000" />
          </div>
        </div>

        <div class="form-group">
          <label>Maksymalna liczba filmów na twórcę</label>
          <input v-model="form.max_videos_per_creator" type="number" min="1" placeholder="1" />
        </div>
      </fieldset>

      <!-- Sekcja 4: Rozliczenia i Stawki -->
      <fieldset>
        <legend>4. Rozliczenie i Wynagrodzenie</legend>

        <div class="grid-2">
          <div class="form-group">
            <label>Stawka za Short / TikTok (PLN)</label>
            <input v-model="form.short_payout" type="number" step="0.01" min="0" placeholder="200.00" />
          </div>

          <div class="form-group">
            <label>Stawka za Długie Wideo / YouTube (PLN)</label>
            <input v-model="form.long_payout" type="number" step="0.01" min="0" placeholder="800.00" />
          </div>
        </div>

        <div class="grid-2">
          <div class="form-group">
            <label>Stawka za 1000 wyświetleń (CPM PLN)</label>
            <input v-model="form.payout_per_views" type="number" step="0.01" min="0" placeholder="15.00" />
          </div>

          <div class="form-group">
            <label>Stawka za kliknięcie w link (CPC PLN)</label>
            <input v-model="form.payout_per_click" type="number" step="0.01" min="0" placeholder="1.50" />
          </div>
        </div>
      </fieldset>

      <button type="submit" class="btn-submit" :disabled="loading">
        {{ loading ? 'Utworzenie kampanii...' : 'Utwórz Kampanię' }}
      </button>

    </form>
  </div>
</template>

<style scoped>
.campaign-container {
  max-width: 800px;
  margin: 2rem auto;
  padding: 2rem;
  background: #ffffff;
  border-radius: 8px;
  box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
  font-family: system-ui, -apple-system, sans-serif;
}

h2 {
  margin-top: 0;
  margin-bottom: 1.5rem;
  color: #2d3748;
}

.campaign-form {
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
}

fieldset {
  border: 1px solid #e2e8f0;
  border-radius: 6px;
  padding: 1.25rem;
  display: flex;
  flex-direction: column;
  gap: 1rem;
}

legend {
  font-weight: 600;
  color: #4a5568;
  padding: 0 0.5rem;
}

.form-group {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.form-group label {
  font-size: 0.875rem;
  font-weight: 500;
  color: #4a5568;
}

input[type="text"],
input[type="number"],
input[type="url"],
select,
textarea {
  padding: 0.6rem;
  border: 1px solid #cbd5e0;
  border-radius: 4px;
  font-size: 0.95rem;
  background-color: #fff;
  transition: border-color 0.2s;
}

input:focus, select:focus, textarea:focus {
  outline: none;
  border-color: #3182ce;
}

.checkbox-group label {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  cursor: pointer;
}

.grid-2 {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.grid-3 {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 1rem;
}

.btn-submit {
  padding: 0.8rem 1.5rem;
  background-color: #3182ce;
  color: white;
  border: none;
  border-radius: 6px;
  font-size: 1rem;
  font-weight: 600;
  cursor: pointer;
  transition: background-color 0.2s;
}

.btn-submit:hover:not(:disabled) {
  background-color: #2b6cb0;
}

.btn-submit:disabled {
  background-color: #a0aec0;
  cursor: not-allowed;
}

.alert {
  padding: 0.75rem 1rem;
  border-radius: 6px;
  margin-bottom: 1rem;
  font-size: 0.9rem;
}

.alert-success {
  background-color: #c6f6d5;
  color: #22543d;
  border: 1px solid #9ae6b4;
}

.alert-danger {
  background-color: #fed7d7;
  color: #742a2a;
  border: 1px solid #feb2b2;
}

@media (max-width: 600px) {
  .grid-2, .grid-3 {
    grid-template-columns: 1fr;
  }
}
</style>