import '../styles/table.css';

export interface Column<T> {
  key: string;
  label: string;
  align?: 'left' | 'right' | 'center';
  mono?: boolean;
  render?: (row: T) => React.ReactNode;
  sortable?: boolean;
}

interface DataTableProps<T> {
  columns: Column<T>[];
  data: T[];
  rowKey: (row: T, index: number) => string;
  onRowClick?: (row: T) => void;
  'aria-label'?: string;
  sortKey?: string;
  sortDir?: 'asc' | 'desc';
  onSort?: (key: string) => void;
}

export function DataTable<T>({
  columns,
  data,
  rowKey,
  onRowClick,
  'aria-label': ariaLabel,
  sortKey,
  sortDir = 'asc',
  onSort,
}: DataTableProps<T>) {
  return (
    <div className="data-table-wrap">
      <table className="data-table" aria-label={ariaLabel}>
        <thead>
          <tr>
            {columns.map((col) => {
              const isSorted = sortKey === col.key;
              return (
                <th
                  key={col.key}
                  className={col.align === 'right' ? 'cell--right' : ''}
                  aria-sort={
                    isSorted
                      ? sortDir === 'asc'
                        ? 'ascending'
                        : 'descending'
                      : undefined
                  }
                  onClick={col.sortable && onSort ? () => onSort(col.key) : undefined}
                  tabIndex={col.sortable ? 0 : undefined}
                  onKeyDown={
                    col.sortable && onSort
                      ? (e) => {
                          if (e.key === 'Enter' || e.key === ' ') {
                            e.preventDefault();
                            onSort(col.key);
                          }
                        }
                      : undefined
                  }
                >
                  {col.label}
                  {col.sortable && (
                    <span className="sort-icon" aria-hidden="true">
                      {isSorted ? (sortDir === 'asc' ? '▲' : '▼') : '⇅'}
                    </span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {data.map((row, idx) => (
            <tr
              key={rowKey(row, idx)}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
              tabIndex={onRowClick ? 0 : undefined}
              onKeyDown={
                onRowClick
                  ? (e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        e.preventDefault();
                        onRowClick(row);
                      }
                    }
                  : undefined
              }
              role={onRowClick ? 'button' : undefined}
              aria-label={onRowClick ? `Open details` : undefined}
            >
              {columns.map((col) => {
                const raw = (row as Record<string, unknown>)[col.key];
                const displayed = col.render ? col.render(row) : (raw as React.ReactNode);
                return (
                  <td
                    key={col.key}
                    className={[
                      col.mono ? 'cell--mono' : '',
                      col.align === 'right' ? 'cell--right' : '',
                    ]
                      .filter(Boolean)
                      .join(' ')}
                  >
                    {displayed === null || displayed === undefined ? (
                      <span className="value-unknown" aria-label="Value unavailable" />
                    ) : (
                      displayed
                    )}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
