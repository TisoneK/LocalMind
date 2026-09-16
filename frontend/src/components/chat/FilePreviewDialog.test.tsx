import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilePreviewDialog } from './FilePreviewDialog';
import { localmindClient } from '@/lib/localmind/client';

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: {
    getFileContent: vi.fn(),
    confirmWrite: vi.fn(),
  },
}));

const mockClient = localmindClient as unknown as {
  getFileContent: ReturnType<typeof vi.fn>;
  confirmWrite: ReturnType<typeof vi.fn>;
};

function textContent(overrides: Record<string, unknown> = {}) {
  return {
    path: '/tmp/demo/a.txt',
    name: 'a.txt',
    extension: 'txt',
    size: 12,
    truncated: false,
    editable: true,
    text: 'first line\nsecond line',
    ...overrides,
  };
}

describe('FilePreviewDialog', () => {
  beforeEach(() => {
    // resetAllMocks (not clearAllMocks): a failed test can leave queued
    // mockResolvedValueOnce values that would otherwise bleed into the next
    // test's renders (clearAllMocks keeps the once-queue).
    vi.resetAllMocks();
  });

  it('renders nothing when no path is given', () => {
    render(<FilePreviewDialog path={null} onClose={() => {}} />);
    expect(screen.queryByText('a.txt')).not.toBeInTheDocument();
  });

  it('fetches and shows text content on open', async () => {
    mockClient.getFileContent.mockResolvedValue(textContent());
    render(<FilePreviewDialog path="/tmp/demo/a.txt" onClose={() => {}} />);

    await waitFor(() => {
      expect(mockClient.getFileContent).toHaveBeenCalledWith('/tmp/demo/a.txt');
    });
    expect(await screen.findByText(/first line/)).toBeInTheDocument();
    expect(screen.getByText('a.txt')).toBeInTheDocument();
  });

  it('renders markdown files through ReactMarkdown', async () => {
    mockClient.getFileContent.mockResolvedValue(
      textContent({ extension: 'md', text: '# Title\n\nsome *body*' })
    );
    render(<FilePreviewDialog path="/tmp/README.md" onClose={() => {}} />);

    expect(await screen.findByRole('heading', { name: 'Title' })).toBeInTheDocument();
  });

  it('renders image files as an inline image', async () => {
    mockClient.getFileContent.mockResolvedValue({
      path: '/tmp/pic.png',
      name: 'pic.png',
      extension: 'png',
      size: 40,
      truncated: false,
      image_data_url: 'data:image/png;base64,QUJD',
    });
    render(<FilePreviewDialog path="/tmp/pic.png" onClose={() => {}} />);

    const img = (await screen.findByRole('img', { name: 'pic.png' })) as HTMLImageElement;
    expect(img.src).toBe('data:image/png;base64,QUJD');
  });

  it('shows an error state when the fetch fails', async () => {
    mockClient.getFileContent.mockResolvedValue(null);
    render(<FilePreviewDialog path="/tmp/gone.txt" onClose={() => {}} />);

    expect(
      await screen.findByText(/could not read this file/i)
    ).toBeInTheDocument();
  });

  it('calls onClose when the close button is clicked', async () => {
    mockClient.getFileContent.mockResolvedValue(textContent());
    const onClose = vi.fn();
    render(<FilePreviewDialog path="/tmp/demo/a.txt" onClose={onClose} />);

    await screen.findByText(/first line/);
    await userEvent.click(screen.getByLabelText('Close preview'));
    expect(onClose).toHaveBeenCalled();
  });

  describe('spreadsheet preview (CSV/XLSX)', () => {
    it('renders sheet tabs and the active sheet table', async () => {
      mockClient.getFileContent.mockResolvedValue(
        textContent({
          extension: 'xlsx',
          editable: false,
          sheets: [
            { name: 'Sales', rows: [['item', 'qty'], ['apple', '3'], ['pear', '2']] },
            { name: 'Notes', rows: [['note'], ['hello']] },
          ],
        })
      );
      render(<FilePreviewDialog path="/tmp/book.xlsx" onClose={() => {}} />);

      // Both tabs + headers + first data row of the active sheet.
      expect(await screen.findByRole('button', { name: /sales/i })).toBeInTheDocument();
      expect(screen.getByRole('button', { name: /notes/i })).toBeInTheDocument();
      expect(screen.getByRole('columnheader', { name: /item/i })).toBeInTheDocument();
      expect(screen.getByRole('cell', { name: /apple/i })).toBeInTheDocument();
      // Notes sheet data is not visible yet.
      expect(screen.queryByRole('cell', { name: /hello/i })).not.toBeInTheDocument();
    });

    it('switches sheets when a tab is clicked', async () => {
      mockClient.getFileContent.mockResolvedValue(
        textContent({
          extension: 'xlsx',
          editable: false,
          sheets: [
            { name: 'Sales', rows: [['item'], ['apple']] },
            { name: 'Notes', rows: [['note'], ['hello']] },
          ],
        })
      );
      render(<FilePreviewDialog path="/tmp/book.xlsx" onClose={() => {}} />);

      await screen.findByRole('cell', { name: /apple/i });
      await userEvent.click(screen.getByRole('button', { name: /notes/i }));
      expect(screen.getByRole('cell', { name: /hello/i })).toBeInTheDocument();
      expect(screen.queryByRole('cell', { name: /apple/i })).not.toBeInTheDocument();
    });

    it('shows the truncation note when the sheet was capped', async () => {
      mockClient.getFileContent.mockResolvedValue(
        textContent({
          extension: 'csv',
          editable: false,
          sheets: [{ name: 'Sheet 1', rows: [['a']], truncated: true }],
        })
      );
      render(<FilePreviewDialog path="/tmp/big.csv" onClose={() => {}} />);

      expect(
        await screen.findByText(/rows.*columns truncated for preview/i)
      ).toBeInTheDocument();
    });
  });

  describe('spreadsheet edit mode', () => {
    it('edits cells and saves the structured sheets through confirmWrite', async () => {
      mockClient.getFileContent
        .mockResolvedValueOnce(
          textContent({
            extension: 'xlsx',
            editable: false,
            sheets: [
              { name: 'Sales', rows: [['item', 'qty'], ['apple', '3'], ['pear', '2']] },
            ],
          })
        )
        .mockResolvedValueOnce(
          textContent({
            extension: 'xlsx',
            editable: false,
            sheets: [
              { name: 'Sales', rows: [['item', 'qty'], ['apple', '9'], ['pear', '2']] },
            ],
          })
        );
      mockClient.confirmWrite.mockResolvedValue({ path: '/tmp/book.xlsx', filename: 'book.xlsx' });
      render(<FilePreviewDialog path="/tmp/book.xlsx" onClose={() => {}} />);

      await screen.findByRole('cell', { name: /apple/i });
      await userEvent.click(screen.getByRole('button', { name: /edit/i }));

      // Cells become inputs — edit qty from 3 to 9 (first data row, 2nd column).
      const qtyInput = screen.getByLabelText('Cell 1,2') as HTMLInputElement;
      expect(qtyInput.value).toBe('3');
      await userEvent.clear(qtyInput);
      await userEvent.type(qtyInput, '9');
      await userEvent.click(screen.getByRole('button', { name: /save/i }));

      expect(mockClient.confirmWrite).toHaveBeenCalledWith(
        '/tmp/book.xlsx',
        '',
        [{ name: 'Sales', rows: [['item', 'qty'], ['apple', '9'], ['pear', '2']] }]
      );
      // Re-fetched preview shows the saved value.
      expect(await screen.findByRole('cell', { name: /9/i })).toBeInTheDocument();
    });

    it('hides the Edit button when a sheet was truncated (would lose rows)', async () => {
      mockClient.getFileContent.mockResolvedValue(
        textContent({
          extension: 'xlsx',
          editable: false,
          sheets: [{ name: 'Big', rows: [['n'], ['1']], truncated: true }],
        })
      );
      render(<FilePreviewDialog path="/tmp/big.xlsx" onClose={() => {}} />);

      // The truncation note confirms the sheet loaded (and Edit must stay hidden).
      await screen.findByText(/rows.*columns truncated for preview/i);
      expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument();
    });

    it('Cancel restores the original cell values', async () => {
      mockClient.getFileContent.mockResolvedValue(
        textContent({
          extension: 'csv',
          editable: false,
          sheets: [{ name: 'Sheet 1', rows: [['name'], ['alice']] }],
        })
      );
      render(<FilePreviewDialog path="/tmp/data.csv" onClose={() => {}} />);

      await screen.findByRole('cell', { name: /alice/i });
      await userEvent.click(screen.getByRole('button', { name: /edit/i }));
      const input = screen.getByLabelText('Cell 1,1');
      await userEvent.clear(input);
      await userEvent.type(input, 'zed');
      await userEvent.click(screen.getByRole('button', { name: /cancel/i }));

      expect(screen.queryByLabelText('Cell 1,1')).not.toBeInTheDocument();
      expect(screen.getByRole('cell', { name: /alice/i })).toBeInTheDocument();
    });
  });

  describe('diff mode', () => {
    const sampleHunks = [
      {
        filePath: '/tmp/demo/a.txt',
        oldStart: 1, oldLines: 3, newStart: 1, newLines: 3,
        lines: [
          { type: 'hunk_header' as const, content: '@@ -1,3 +1,3 @@', oldLine: 1, newLine: 1 },
          { type: 'removed' as const, content: 'first line', oldLine: 1 },
          { type: 'added' as const, content: 'first line edited', newLine: 1 },
          { type: 'context' as const, content: 'second line', oldLine: 2, newLine: 2 },
        ],
      },
    ];

    it('shows the Diff tab when hunks exist and renders the DiffBlock', async () => {
      mockClient.getFileContent.mockResolvedValue(textContent());
      render(
        <FilePreviewDialog
          path="/tmp/demo/a.txt"
          onClose={() => {}}
          diffs={{ '/tmp/demo/a.txt': { hunks: sampleHunks, language: 'txt', filePath: '/tmp/demo/a.txt', additions: 1, deletions: 1 } }}
        />
      );

      await screen.findByText(/first line/);
      await userEvent.click(screen.getByTestId('preview-mode-diff'));

      // DiffBlock renders the before/after lines + stats.
      expect(await screen.findByText(/first line edited/)).toBeInTheDocument();
      expect(screen.getByText('first line')).toBeInTheDocument();
      // Stats appear in both the header and footer bars — at least one each.
      expect(screen.getAllByText('+1').length).toBeGreaterThan(0);
      expect(screen.getAllByText('-1').length).toBeGreaterThan(0);
    });

    it('hides the Diff tab when no hunks exist for the file', async () => {
      mockClient.getFileContent.mockResolvedValue(textContent());
      render(<FilePreviewDialog path="/tmp/demo/a.txt" onClose={() => {}} />);

      await screen.findByText(/first line/);
      expect(screen.queryByTestId('preview-mode-diff')).not.toBeInTheDocument();
    });

    it('switches back to Preview from Diff', async () => {
      mockClient.getFileContent.mockResolvedValue(textContent());
      render(
        <FilePreviewDialog
          path="/tmp/demo/a.txt"
          onClose={() => {}}
          diffs={{ '/tmp/demo/a.txt': { hunks: sampleHunks, language: 'txt', filePath: '/tmp/demo/a.txt' } }}
        />
      );

      await screen.findByText(/first line/);
      await userEvent.click(screen.getByTestId('preview-mode-diff'));
      expect(await screen.findByText(/first line edited/)).toBeInTheDocument();

      await userEvent.click(screen.getByTestId('preview-mode-preview'));
      // Preview content returns; diff lines gone.
      expect(screen.getByText(/second line/)).toBeInTheDocument();
      expect(screen.queryByText(/first line edited/)).not.toBeInTheDocument();
    });

    it('Edit tab starts edit mode and Cancel returns to Preview', async () => {
      mockClient.getFileContent.mockResolvedValue(textContent());
      render(
        <FilePreviewDialog
          path="/tmp/demo/a.txt"
          onClose={() => {}}
          diffs={{ '/tmp/demo/a.txt': { hunks: sampleHunks, language: 'txt', filePath: '/tmp/demo/a.txt' } }}
        />
      );

      await screen.findByText(/first line/);
      await userEvent.click(screen.getByTestId('preview-mode-edit'));
      expect(screen.getByLabelText('Edit file content')).toBeInTheDocument();
      await userEvent.click(screen.getByRole('button', { name: /cancel/i }));
      expect(screen.queryByLabelText('Edit file content')).not.toBeInTheDocument();
      expect(screen.getByTestId('preview-mode-preview')).toBeInTheDocument();
    });
  });

  describe('edit mode', () => {
    it('shows an Edit button for text files and edits the draft in a textarea', async () => {
      mockClient.getFileContent.mockResolvedValue(textContent());
      render(<FilePreviewDialog path="/tmp/demo/a.txt" onClose={() => {}} />);

      await screen.findByText(/first line/);
      await userEvent.click(screen.getByRole('button', { name: /edit/i }));

      const textarea = screen.getByLabelText('Edit file content') as HTMLTextAreaElement;
      expect(textarea.value).toBe('first line\nsecond line');
      await userEvent.clear(textarea);
      await userEvent.type(textarea, 'edited content');
      expect(textarea.value).toBe('edited content');
    });

    it('saves through confirmWrite and refreshes the preview on success', async () => {
      mockClient.getFileContent.mockResolvedValueOnce(textContent()).mockResolvedValueOnce(
        textContent({ text: 'edited content', size: 15 })
      );
      mockClient.confirmWrite.mockResolvedValue({ path: '/tmp/demo/a.txt', filename: 'a.txt' });
      render(<FilePreviewDialog path="/tmp/demo/a.txt" onClose={() => {}} />);

      await screen.findByText(/first line/);
      await userEvent.click(screen.getByRole('button', { name: /edit/i }));
      const textarea = screen.getByLabelText('Edit file content');
      await userEvent.clear(textarea);
      await userEvent.type(textarea, 'edited content');
      await userEvent.click(screen.getByRole('button', { name: /save/i }));

      expect(mockClient.confirmWrite).toHaveBeenCalledWith('/tmp/demo/a.txt', 'edited content');
      expect(await screen.findByText(/edited content/)).toBeInTheDocument();
      expect(screen.getByText('Saved')).toBeInTheDocument();
      // Edit mode exits back to read-only view.
      expect(screen.queryByLabelText('Edit file content')).not.toBeInTheDocument();
    });

    it('keeps the editor open and shows an error when the save fails', async () => {
      mockClient.getFileContent.mockResolvedValue(textContent());
      mockClient.confirmWrite.mockRejectedValue(new Error('boom'));
      render(<FilePreviewDialog path="/tmp/demo/a.txt" onClose={() => {}} />);

      await screen.findByText(/first line/);
      await userEvent.click(screen.getByRole('button', { name: /edit/i }));
      await userEvent.click(screen.getByRole('button', { name: /save/i }));

      expect(await screen.findByText(/save failed/i)).toBeInTheDocument();
      expect(screen.getByLabelText('Edit file content')).toBeInTheDocument();
    });

    it('hides the Edit button for office docs (parsed text is not the file)', async () => {
      mockClient.getFileContent.mockResolvedValue(
        textContent({ extension: 'docx', editable: false, text: 'Parsed doc text' })
      );
      render(<FilePreviewDialog path="/tmp/report.docx" onClose={() => {}} />);

      await screen.findByText(/parsed doc text/i);
      expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument();
    });

    it('hides the Edit button for images', async () => {
      mockClient.getFileContent.mockResolvedValue({
        path: '/tmp/pic.png',
        name: 'pic.png',
        extension: 'png',
        size: 40,
        truncated: false,
        editable: false,
        image_data_url: 'data:image/png;base64,QUJD',
      });
      render(<FilePreviewDialog path="/tmp/pic.png" onClose={() => {}} />);

      await screen.findByRole('img', { name: 'pic.png' });
      expect(screen.queryByRole('button', { name: /edit/i })).not.toBeInTheDocument();
    });
  });
});
