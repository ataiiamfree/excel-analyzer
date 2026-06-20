import { useMemo, useState } from "react";
import { Download, Maximize2 } from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import {
  flexRender,
  getCoreRowModel,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable
} from "@tanstack/react-table";
import type { ColumnDef, SortingState } from "@tanstack/react-table";

import { fetchTablePreview } from "../api/http";
import type { Artifact } from "../api/types";

interface TablePreviewProps {
  artifact: Artifact;
}

export default function TablePreview({ artifact }: TablePreviewProps) {
  const [globalFilter, setGlobalFilter] = useState("");
  const [sorting, setSorting] = useState<SortingState>([]);
  const previewUrl = artifact.preview_url ?? "";
  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact-preview", artifact.id],
    queryFn: () => fetchTablePreview(previewUrl),
    enabled: Boolean(previewUrl)
  });
  const columns = useMemo<ColumnDef<Record<string, unknown>>[]>(
    () =>
      (data?.columns ?? []).map((column) => ({
        accessorKey: column,
        header: column,
        cell: (info) => String(info.getValue() ?? "")
      })),
    [data?.columns]
  );
  const table = useReactTable({
    data: data?.rows ?? [],
    columns,
    state: { sorting, globalFilter },
    onSortingChange: setSorting,
    onGlobalFilterChange: setGlobalFilter,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel()
  });

  return (
    <div className="preview-card">
      <div className="cap">
        <span className="name">{artifact.name}</span>
        <span className="meta">{data ? `${data.row_count} 行` : `${Math.ceil(artifact.size / 1024)} KB`}</span>
        <a className="act" href={artifact.url} download title="下载">
          <Download size={13} />
        </a>
      </div>
      <div className="toolbar">
        <input
          placeholder="筛选表格..."
          value={globalFilter}
          onChange={(event) => setGlobalFilter(event.target.value)}
        />
        <span className="pip">{table.getRowModel().rows.length} 行</span>
        <button className="act" title="预览范围">
          <Maximize2 size={13} />
        </button>
      </div>
      <div className="table-wrap">
        {isLoading ? <div style={{ padding: 14, color: "var(--ink-3)" }}>加载预览...</div> : null}
        {error ? <div style={{ padding: 14, color: "var(--accent)" }}>暂时无法预览该表格。</div> : null}
        {data ? (
          <table className="dt">
            <thead>
              {table.getHeaderGroups().map((headerGroup) => (
                <tr key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <th key={header.id} onClick={header.column.getToggleSortingHandler()}>
                      {flexRender(header.column.columnDef.header, header.getContext())}
                      {header.column.getIsSorted() ? <span className="ar">▼</span> : null}
                    </th>
                  ))}
                </tr>
              ))}
            </thead>
            <tbody>
              {table.getRowModel().rows.map((row) => (
                <tr key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <td key={cell.id}>{flexRender(cell.column.columnDef.cell, cell.getContext())}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        ) : null}
      </div>
    </div>
  );
}
