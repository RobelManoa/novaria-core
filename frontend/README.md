# Frontend (React + Vite + TypeScript)

```bash
npm install
npm run dev        # http://localhost:5173 (proxy /api vers le backend)
npm test           # vitest + couverture (coverage/lcov.info)
npm run lint && npm run format:check
npm run build
```

Premier commit utile : générer `package-lock.json` (`npm install`) puis le versionner ; la CI passe alors à `npm ci`.
