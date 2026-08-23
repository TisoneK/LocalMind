import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { FilePreviewDialog } from './FilePreviewDialog';
import { localmindClient } from '@/lib/localmind/client';

vi.mock('@/lib/localmind/client', () => ({
  localmindClient: {
    getFileContent: vi.fn(),
  },
}));

const mockClient = localmindClient as unknown as {
  getFileContent: ReturnType<typeof vi.fn>;
};

function textContent(overrides: Record<string, unknown> = {}) {
  return {
    path: '/tmp/demo/a.txt',
    name: 'a.txt',
    extension: 'txt',
    size: 12,
    truncated: false,
    text: 'first line\nsecond line',
    ...overrides,
  };
}

describe('FilePreviewDialog', () => {
  beforeEach(() => {
    vi.clearAllMocks();
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
});
