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
    tax_id: `PL${Math.floor(1000000000 + Math.random() * 9000000000)}`,
    password: 'Test1234!'
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
    password: 'Test1234!',
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

