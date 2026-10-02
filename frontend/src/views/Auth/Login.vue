<script setup>
import { reactive, ref } from 'vue'

const emit = defineEmits(['logged-in'])

const mode = ref('login')
const form = reactive({
  account_type: 'company',
  login: '',
  name: '',
  username: '',
  full_name: '',
  password: ''
})
const passwordConfirmation = ref('')
const loading = ref(false)
const errorMessage = ref('')

const parseError = (data, fallback) => {
  if (Array.isArray(data.detail)) return data.detail.map(item => item.msg).join('; ')
  return data.detail || fallback
}

const handleSubmit = async () => {
  loading.value = true
  errorMessage.value = ''

  try {
    if (mode.value === 'register' && form.password !== passwordConfirmation.value) {
      throw new Error('Hasła muszą być takie same')
    }

    const registrationPayload = form.account_type === 'company'
      ? {
          name: form.name,
          email: form.login,
          password: form.password
        }
      : {
          username: form.username,
          full_name: form.full_name || null,
          email: form.login,
          password: form.password
        }
    const endpoint = mode.value === 'login'
      ? 'http://localhost:8000/api/auth/login'
      : `http://localhost:8000/api/${form.account_type === 'company' ? 'companies' : 'creators'}`
    const payload = mode.value === 'login'
      ? { account_type: form.account_type, login: form.login, password: form.password }
      : registrationPayload

    const response = await fetch(endpoint, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
    const data = await response.json()

    if (!response.ok) {
      throw new Error(parseError(data, mode.value === 'login' ? 'Nie udało się zalogować' : 'Nie udało się utworzyć konta'))
    }

    if (mode.value === 'register') {
      form.password = ''
      passwordConfirmation.value = ''
      mode.value = 'login'
      errorMessage.value = 'Konto utworzone. Możesz się teraz zalogować.'
      return
    }

    localStorage.setItem('waggi_session', JSON.stringify(data))
    emit('logged-in', data)
  } catch (error) {
    errorMessage.value = error.message
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <main class="login-page">
    <section class="login-panel">
      <p class="login-eyebrow">WAGGI / USER PANEL</p>
      <h1>{{ mode === 'login' ? 'Log in to Waggi' : 'Create a Waggi account' }}</h1>
      <p class="login-subtitle">Choose your account type to {{ mode === 'login' ? 'access your dashboard.' : 'start collaborating.' }}</p>

      <div class="account-switcher" role="tablist" aria-label="Account type">
        <button
          type="button"
          :class="{ selected: form.account_type === 'company' }"
          @click="form.account_type = 'company'"
        >
          Company
        </button>
        <button
          type="button"
          :class="{ selected: form.account_type === 'creator' }"
          @click="form.account_type = 'creator'"
        >
          Creator
        </button>
      </div>

      <div v-if="errorMessage" class="alert alert-danger">{{ errorMessage }}</div>

      <form @submit.prevent="handleSubmit" class="login-form">
        <label v-if="mode === 'register' && form.account_type === 'company'" class="form-group">
          <span>Company name</span>
          <input v-model="form.name" type="text" autocomplete="organization" required />
        </label>
        <label v-if="mode === 'register' && form.account_type === 'creator'" class="form-group">
          <span>Username</span>
          <input v-model="form.username" type="text" autocomplete="username" required />
        </label>
        <label v-if="mode === 'register' && form.account_type === 'creator'" class="form-group">
          <span>Full name</span>
          <input v-model="form.full_name" type="text" autocomplete="name" />
        </label>
        <label class="form-group">
          <span>{{ form.account_type === 'company' ? 'Email address' : 'Email or username' }}</span>
          <input
            v-model="form.login"
            :type="form.account_type === 'company' ? 'email' : 'text'"
            autocomplete="username"
            required
          />
        </label>
        <label class="form-group">
          <span>Password</span>
          <input v-model="form.password" type="password" :autocomplete="mode === 'login' ? 'current-password' : 'new-password'" minlength="8" required />
        </label>
        <label v-if="mode === 'register'" class="form-group">
          <span>Confirm password</span>
          <input v-model="passwordConfirmation" type="password" autocomplete="new-password" minlength="8" required />
        </label>
        <button class="btn-submit login-submit" type="submit" :disabled="loading">
          {{ loading ? 'Processing...' : (mode === 'login' ? 'Log in' : 'Create account') }}
        </button>
      </form>
      <button class="auth-mode-link" type="button" @click="mode = mode === 'login' ? 'register' : 'login'; errorMessage = ''">
        {{ mode === 'login' ? 'Don’t have an account? Sign up' : 'Already have an account? Log in' }}
      </button>
    </section>
  </main>
</template>