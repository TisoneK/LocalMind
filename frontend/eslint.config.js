import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'

// Flat config for LocalMind frontend (React 19 + TypeScript 5 + Vite 6).
//
// ESLint v9+ uses flat config (eslint.config.js) instead of .eslintrc.*.
// This file replaces the missing config that caused `npm run lint` to fail
// with "ESLint couldn't find an eslint.config.(js|mjs|cjs) file".
export default tseslint.config(
  {
    ignores: ['dist/**', 'node_modules/**', '*.config.ts', '*.config.js'],
  },
  {
    files: ['**/*.{ts,tsx}'],
    extends: [
      js.configs.recommended,
      ...tseslint.configs.recommended,
    ],
    languageOptions: {
      ecmaVersion: 2022,
      globals: {
        ...globals.browser,
        ...globals.es2022,
      },
      parserOptions: {
        ecmaFeatures: { jsx: true },
      },
    },
    plugins: {
      'react-hooks': reactHooks,
      'react-refresh': reactRefresh,
    },
    rules: {
      ...reactHooks.configs.recommended.rules,
      'react-refresh/only-export-components': [
        'warn',
        { allowConstantExport: true },
      ],
      // Allow unused vars that start with _ (common convention for
      // intentionally-unused callback params in event handlers).
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
      // React 19 doesn't require React in scope for JSX (new JSX transform).
      'react/react-in-jsx-scope': 'off',
      // Allow `any` with a warning — the codebase uses it intentionally
      // in API client code where response shapes are dynamic.
      '@typescript-eslint/no-explicit-any': 'warn',
      // React 19's set-state-in-effect rule is valuable for new code but
      // flags many intentional patterns in existing code (e.g. refreshing
      // data on mount). Warn instead of error for now.
      'react-hooks/set-state-in-effect': 'warn',
    },
  },
)
