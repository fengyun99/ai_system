import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import type { PayloadAction } from '@reduxjs/toolkit'
import type { InfoData, InfoUser } from '../types/api'
import { get, post } from '../lib/api'

export type UserInfo = InfoUser

interface AuthState {
  token: string | null
  user: UserInfo | null
  roles: string[]
  roleNames: string[]
  permissions: string[]
  dataScope: number
}

const stored = localStorage.getItem('token')

export const fetchInfo = createAsyncThunk('auth/fetchInfo', async () => {
  return await get<InfoData>('/getInfo')
})

export const logout = createAsyncThunk('auth/logout', async () => {
  try {
    await post('/logout')
  } catch {
    /* 忽略登出失败 */
  }
  localStorage.removeItem('token')
  window.location.href = '/login'
})

const authSlice = createSlice({
  name: 'auth',
  initialState: {
    token: stored,
    user: null,
    roles: [],
    roleNames: [],
    permissions: [],
    dataScope: 2,
  } as AuthState,
  reducers: {
    setToken(state, action) {
      state.token = action.payload
      localStorage.setItem('token', action.payload)
    },
  },
  extraReducers: (builder) => {
    builder.addCase(fetchInfo.fulfilled, (state, action: PayloadAction<InfoData>) => {
      state.user = action.payload.user
      state.roles = action.payload.roles
      state.roleNames = action.payload.role_names
      state.permissions = action.payload.permissions
      state.dataScope = action.payload.data_scope
    })
  },
})

export const { setToken } = authSlice.actions
export default authSlice.reducer
