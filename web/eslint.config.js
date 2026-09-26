import tseslint from 'typescript-eslint'
import reactHooks from 'eslint-plugin-react-hooks'

// Only the hook rules: data hooks must list useDataNonce() in their deps or they never refetch.
export default tseslint.config(
  { ignores: ['dist', 'node_modules', 'public'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    languageOptions: { parser: tseslint.parser },
    plugins: { 'react-hooks': reactHooks },
    rules: {
      'react-hooks/rules-of-hooks': 'error',
      'react-hooks/exhaustive-deps': 'error',
    },
  },
)
