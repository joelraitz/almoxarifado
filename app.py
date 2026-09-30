'use client';

import React, { useState } from 'react';
import { Upload, FileText, CheckCircle2, AlertCircle, Loader2, X } from 'lucide-react';

interface ProdutoItem {
  SKU: string;
  'Nome do Produto': string;
  Categoria: string;
  'Estoque Mínimo': number;
  'Preço Unitário': number;
  'Quantidade Inicial': number;
}

export default function GestaoProdutosPage() {
  const [file, setFile] = useState(null);
  const [previewData, setPreviewData] = useState([]);
  const [loading, setLoading] = useState(false);
  const [importing, setImporting] = useState(false);
  const [successMessage, setSuccessMessage] = useState(null);
  const [errorMessage, setErrorMessage] = useState(null);

  // Função para ler o CSV e alimentar a pré-visualização
  const handleFileUpload = (e: React.ChangeEvent) => {
    const uploadedFile = e.target.files?.[0];
    if (!uploadedFile) return;

    setFile(uploadedFile);
    setLoading(true);
    setErrorMessage(null);
    setSuccessMessage(null);

    const reader = new FileReader();
    reader.onload = (event) => {
      try {
        const text = event.target?.result as string;
        const lines = text.split('\n').filter(line => line.trim() !== '');
        if (lines.length < 2) {
          throw new Error('O arquivo está vazio ou sem dados válidos.');
        }

        // Identifica o separador (vírgula ou ponto e vírgula)
        const separator = lines[0].includes(';') ? ';' : ',';
        const headers = lines[0].split(separator).map(h => h.trim().replace(/^["']|["']$/g, ''));

        const parsedData: ProdutoItem[] = [];

        for (let i = 1; i < lines.length; i++) {
          const currentLine = lines[i].split(separator).map(val => val.trim().replace(/^["']|["']$/g, ''));
          if (currentLine.length >= headers.length) {
            parsedData.push({
              SKU: currentLine[0] || '',
              'Nome do Produto': currentLine[1] || '',
              Categoria: currentLine[2] || '',
              'Estoque Mínimo': Number(currentLine[3]) || 0,
              'Preço Unitário': Number(currentLine[4].replace(',', '.')) || 0,
              'Quantidade Inicial': Number(currentLine[5]) || 0,
            });
          }
        }

        setPreviewData(parsedData);
      } catch (err: any) {
        setErrorMessage('Erro ao processar o arquivo CSV: ' + err.message);
      } finally {
        setLoading(false);
      }
    };

    reader.readAsText(uploadedFile, 'UTF-8');
  };

  // Função para limpar o arquivo selecionado
  const handleRemoveFile = () => {
    setFile(null);
    setPreviewData([]);
    setSuccessMessage(null);
    setErrorMessage(null);
  };

  // Função acionada ao clicar em Processar Importação
  const handleProcessImport = async () => {
    if (previewData.length === 0) return;

    setImporting(true);
    setErrorMessage(null);

    try {
      // Simulação do envio em lote para o backend (substitua pela chamada real fetch/axios)
      // Exemplo: await fetch('/api/produtos/import', { method: 'POST', body: JSON.stringify(previewData) });
      await new Promise(resolve => setTimeout(resolve, 1500));

      setSuccessMessage(`${previewData.length} produtos importados com sucesso para o almoxarifado!`);
      setFile(null);
      setPreviewData([]);
    } catch (err: any) {
      setErrorMessage('Erro ao salvar os produtos no servidor: ' + err.message);
    } finally {
      setImporting(false);
    }
  };

  return (
