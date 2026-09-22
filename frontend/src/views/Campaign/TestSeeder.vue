<script setup>
import { ref } from 'vue'

const emit = defineEmits(['data-seeded'])

const createdCompany = ref(null)
const createdCreator = ref(null)
const loadingCompany = ref(false)
const loadingCreator = ref(false)
const errorMessage = ref('')

// Generowanie testowej firmy
const createTestCompany = async () => {
  loadingCompany.value = true
  errorMessage.value = ''
  createdCompany.value = null

  const randomId = Math.floor(Math.random() * 1000)
  
  const payload = {
    name: `TechBrand Corp ${randomId}`,
    email: `contact${randomId}@techbrand.com`,
    website_url: 'https://techbrand.com',
    logo_url: 'https://via.placeholder.com/150',
    description: 'Innowacyjna firma technologiczna tworząca akcesoria gamingowe.',
    industry: 'Gaming & Tech',
    tax_id: `PL${Math.floor(1000000000 + Math.random() * 9000000000)}`
  }

  try {
    const res = await fetch('http://localhost:8000/api/companies', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    const data = await res.json()

    if (!res.ok) {
      throw new Error(data.detail || 'Błąd podczas tworzenia firmy')
    }

    createdCompany.value = data
    emit('data-seeded', { type: 'company', data })
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    loadingCompany.value = false
  }
}

// Generowanie testowego twórcy
const createTestCreator = async () => {
  loadingCreator.value = true
  errorMessage.value = ''
  createdCreator.value = null

  const randomId = Math.floor(Math.random() * 1000)

  const payload = {
    username: `creator_${randomId}`,
    full_name: `Jan Kowalski ${randomId}`,
    email: `creator${randomId}@example.com`,
    avatar_url: 'https://via.placeholder.com/150',
    bio: 'Twórca wideo technologicznych i recenzent sprzętu.',
    languages: ['PL', 'EN'],
    categories: ['Gaming', 'Tech'],
    platform_stats: {
      youtube: { channel_id: 'UC_test_123', subscribers: 25000, avg_views: 8500 },
      tiktok: { handle: `@creator_${randomId}`, followers: 120000, avg_views: 35000 }
    }
  }

  try {
    const res = await fetch('http://localhost:8000/api/creators', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })

    const data = await res.json()

    if (!res.ok) {
      throw new Error(data.detail || 'Błąd podczas tworzenia twórcy')
    }

    createdCreator.value = data
    emit('data-seeded', { type: 'creator', data })
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    loadingCreator.value = false
  }
}
</script>

<template>
  <div class="seeder-container">
    <h2>Generator danych testowych</h2>
    <p>Użyj poniższych przycisków, aby wygenerować obiekty w bazie danych PostgreSQL.</p>

    <div v-if="errorMessage" class="alert alert-danger">
      {{ errorMessage }}
    </div>

    <div class="cards-grid">
      <!-- Karta Firmy -->
      <div class="card">
        <h3>Testowa Firma (Company)</h3>
        <p>Tworzy profil firmy z losowym NIP-em i adresem e-mail.</p>
        <button @click="createTestCompany" :disabled="loadingCompany" class="btn">
          {{ loadingCompany ? 'Tworzenie...' : 'Stwórz testową Firmę' }}
        </button>

        <div v-if="createdCompany" class="result-box">
          <p class="success-tag">Utworzono sukcesem!</p>
          <p><strong>ID:</strong> {{ createdCompany.id }}</p>
          <p><strong>Nazwa:</strong> {{ createdCompany.name }}</p>
          <p><strong>Email:</strong> {{ createdCompany.email }}</p>
        </div>
      </div>

      <!-- Karta Twórcy -->
      <div class="card">
        <h3>Testowy Twórca (Creator)</h3>
        <p>Tworzy profil twórcy wraz ze statystykami YouTube/TikTok.</p>
        <button @click="createTestCreator" :disabled="loadingCreator" class="btn btn-green">
          {{ loadingCreator ? 'Tworzenie...' : 'Stwórz testowego Twórcę' }}
        </button>

        <div v-if="createdCreator" class="result-box">
          <p class="success-tag">Utworzono sukcesem!</p>
          <p><strong>ID:</strong> {{ createdCreator.id }}</p>
          <p><strong>Username:</strong> {{ createdCreator.username }}</p>
          <p><strong>Subskrypcje YT:</strong> {{ createdCreator.platform_stats?.youtube?.subscribers }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.seeder-container {
  max-width: 800px;
  margin: 2rem auto;
  padding: 1.5rem;
  font-family: system-ui, sans-serif;
}

.cards-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1.5rem;
  margin-top: 1.5rem;
}

.card {
  border: 1px solid #e2e8f0;
  border-radius: 8px;
  padding: 1.25rem;
  background: #ffffff;
  display: flex;
  flex-direction: column;
}

.card p {
  color: #4a5568;
  font-size: 0.9rem;
}

.btn {
  width: 100%;
  padding: 0.6rem;
  background-color: #3182ce;
  color: white;
  border: none;
  border-radius: 6px;
  cursor: pointer;
  font-weight: 600;
  margin-top: auto;
  transition: background-color 0.2s;
}

.btn:hover:not(:disabled) {
  background-color: #2b6cb0;
}

.btn:disabled {
  background-color: #a0aec0;
  cursor: not-allowed;
}

.btn-green { 
  background-color: #38a169; 
}

.btn-green:hover:not(:disabled) {
  background-color: #2f855a;
}

.result-box {
  margin-top: 1rem;
  padding: 0.75rem;
  background: #f7fafc;
  border: 1px solid #edf2f7;
  border-radius: 6px;
  font-size: 0.85rem;
}

.result-box p {
  margin: 0.25rem 0;
  color: #2d3748;
}

.success-tag {
  color: #2f855a !important;
  font-weight: bold;
  margin-bottom: 0.5rem;
}

.alert-danger {
  padding: 0.75rem;
  background-color: #fed7d7;
  color: #742a2a;
  border: 1px solid #feb2b2;
  border-radius: 6px;
  margin-top: 1rem;
  font-size: 0.9rem;
}

@media (max-width: 600px) {
  .cards-grid {
    grid-template-columns: 1fr;
  }
}
</style>