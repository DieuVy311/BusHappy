import { defineConfig } from 'vite';
import path from 'path';

export default defineConfig({
    root: './',
    publicDir: 'public',
    build: {
        outDir: 'dist',
        emptyOutDir: true,
        sourcemap: true,
        rollupOptions: {
            input: {
                main: path.resolve(__dirname, 'index.html')
            }
        }
    },
    resolve: {
        alias: {
            '@': path.resolve(__dirname, './'),
        },
    },
    server: {
        port: 3000,
        open: true,
        proxy: {
            '/api': {
                target: process.env.VITE_API_URL || 'http://localhost:5000',
                changeOrigin: true,
                rewrite: (path) => path
            }
        }
    },
    preview: {
        port: 4173,
        open: true
    },
    define: {
        'import.meta.env.VITE_API_URL': JSON.stringify(process.env.VITE_API_URL || 'http://localhost:5000')
    }
});
