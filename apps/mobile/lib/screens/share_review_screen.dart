import 'package:flutter/material.dart';
import '../core/config/api_config.dart';
import '../core/network/api_client.dart';
import '../core/share/shared_content.dart';
import '../core/theme/app_theme.dart';
import '../models/capture.dart';
import 'capture_detail_screen.dart';

/// Screen for reviewing, editing, and saving incoming content shared from Android Share Sheet.
class ShareReviewScreen extends StatefulWidget {
  final SharedContent sharedContent;
  final ApiClient? apiClient;
  final VoidCallback? onCancel;
  final void Function(Capture created)? onSaved;

  const ShareReviewScreen({
    super.key,
    required this.sharedContent,
    this.apiClient,
    this.onCancel,
    this.onSaved,
  });

  @override
  State<ShareReviewScreen> createState() => _ShareReviewScreenState();
}

class _ShareReviewScreenState extends State<ShareReviewScreen> {
  late final ApiClient _client;
  late SourceType _selectedType;

  final _formKey = GlobalKey<FormState>();
  late final TextEditingController _urlController;
  late final TextEditingController _titleController;
  late final TextEditingController _contentController;

  bool _isSubmitting = false;
  String? _submitError;

  @override
  void initState() {
    super.initState();
    _client = widget.apiClient ?? ApiClient();
    _selectedType = widget.sharedContent.sourceType;

    _urlController = TextEditingController(
      text: widget.sharedContent.url ??
          (widget.sharedContent.type == SharedContentType.url
              ? widget.sharedContent.rawText
              : ''),
    );

    _titleController = TextEditingController(
      text: widget.sharedContent.title ?? '',
    );

    _contentController = TextEditingController(
      text: widget.sharedContent.text ??
          (widget.sharedContent.type == SharedContentType.text
              ? widget.sharedContent.rawText
              : ''),
    );
  }

  @override
  void dispose() {
    _urlController.dispose();
    _titleController.dispose();
    _contentController.dispose();
    if (widget.apiClient == null) {
      _client.dispose();
    }
    super.dispose();
  }

  Future<void> _submit() async {
    if (_isSubmitting) return;

    FocusScope.of(context).unfocus();

    if (!_formKey.currentState!.validate()) {
      return;
    }

    setState(() {
      _isSubmitting = true;
      _submitError = null;
    });

    try {
      final payload = CaptureCreate(
        sourceType: _selectedType,
        originalUrl:
            _selectedType == SourceType.url ? _urlController.text.trim() : null,
        title: _titleController.text.trim().isNotEmpty
            ? _titleController.text.trim()
            : null,
        content: _contentController.text.trim().isNotEmpty
            ? _contentController.text.trim()
            : null,
      );

      final created = await _client.createCapture(payload);

      if (mounted) {
        widget.onSaved?.call(created);

        // Replace review screen with CaptureDetailScreen
        Navigator.of(context).pushReplacement(
          MaterialPageRoute(
            builder: (_) => CaptureDetailScreen(
              captureId: created.id,
              initialCapture: created,
              apiClient: _client,
            ),
          ),
        );
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _submitError = e.toString();
        });
      }
    } finally {
      if (mounted) {
        setState(() => _isSubmitting = false);
      }
    }
  }

  void _cancel() {
    if (_isSubmitting) return;
    widget.onCancel?.call();
    Navigator.of(context).maybePop();
  }

  @override
  Widget build(BuildContext context) {
    final isUrl = _selectedType == SourceType.url;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Review Shared Content'),
        leading: IconButton(
          icon: const Icon(Icons.close_rounded),
          tooltip: 'Cancel share',
          onPressed: _isSubmitting ? null : _cancel,
        ),
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 16),
        child: Form(
          key: _formKey,
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // Detected Type Banner
              Container(
                width: double.infinity,
                padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(10),
                  border: Border.all(color: AppTheme.border),
                ),
                child: Row(
                  children: [
                    Icon(
                      widget.sharedContent.type == SharedContentType.url
                          ? Icons.share_location_rounded
                          : Icons.article_outlined,
                      size: 18,
                      color: AppTheme.primaryLight,
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Text(
                        widget.sharedContent.type == SharedContentType.url
                            ? 'Detected Web Link from Android Share Sheet'
                            : 'Detected Text Note from Android Share Sheet',
                        style: const TextStyle(
                          color: AppTheme.textPrimary,
                          fontSize: 12.5,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 18),

              // Segmented Type Selector
              Container(
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(12),
                  border: Border.all(color: AppTheme.border),
                ),
                padding: const EdgeInsets.all(4),
                child: Row(
                  children: [
                    Expanded(
                      child: _TypeTab(
                        label: 'Web Link',
                        icon: Icons.link_rounded,
                        isSelected: isUrl,
                        onTap: () => setState(() {
                          _selectedType = SourceType.url;
                          _submitError = null;
                        }),
                      ),
                    ),
                    Expanded(
                      child: _TypeTab(
                        label: 'Text Note',
                        icon: Icons.edit_note_rounded,
                        isSelected: !isUrl,
                        onTap: () => setState(() {
                          _selectedType = SourceType.text;
                          _submitError = null;
                        }),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 20),

              // Error Display
              if (_submitError != null) ...[
                Container(
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(
                    color: AppTheme.statusFailed.withValues(alpha: 0.1),
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(
                      color: AppTheme.statusFailed.withValues(alpha: 0.3),
                    ),
                  ),
                  child: Row(
                    children: [
                      const Icon(Icons.error_outline,
                          size: 18, color: AppTheme.statusFailed),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          _submitError!,
                          style: const TextStyle(
                            color: AppTheme.statusFailed,
                            fontSize: 12.5,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(height: 16),
              ],

              // URL Form Fields
              if (isUrl) ...[
                const Text(
                  'Web URL *',
                  style: TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _urlController,
                  keyboardType: TextInputType.url,
                  textInputAction: TextInputAction.next,
                  maxLength: 2048,
                  decoration: const InputDecoration(
                    hintText: 'https://example.com/article',
                    prefixIcon: Icon(Icons.public_rounded, size: 18),
                    counterText: '',
                  ),
                  validator: (val) {
                    if (val == null || val.trim().isEmpty) {
                      return 'URL is required';
                    }
                    final trimmed = val.trim();
                    if (!ApiConfig.isValidUrl(trimmed)) {
                      return 'Please enter a valid absolute HTTP or HTTPS URL';
                    }
                    final uri = Uri.tryParse(trimmed);
                    if (uri == null || uri.host.isEmpty) {
                      return 'Please enter a valid absolute URL (e.g. https://example.com)';
                    }
                    return null;
                  },
                ),
                const SizedBox(height: 16),
                const Text(
                  'Title (Optional)',
                  style: TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _titleController,
                  textInputAction: TextInputAction.next,
                  maxLength: 512,
                  decoration: const InputDecoration(
                    hintText: 'Custom title for this web page',
                    counterText: '',
                  ),
                ),
                const SizedBox(height: 16),
                const Text(
                  'Context / Notes (Optional)',
                  style: TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _contentController,
                  maxLines: 4,
                  maxLength: 1000000,
                  decoration: const InputDecoration(
                    hintText: 'Explanatory context or personal notes for this link',
                    counterText: '',
                  ),
                ),
              ],

              // Text Note Form Fields
              if (!isUrl) ...[
                const Text(
                  'Note Title (Optional)',
                  style: TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _titleController,
                  textInputAction: TextInputAction.next,
                  maxLength: 512,
                  decoration: const InputDecoration(
                    hintText: 'Title for your note or idea',
                    counterText: '',
                  ),
                ),
                const SizedBox(height: 16),
                const Text(
                  'Note Content *',
                  style: TextStyle(
                    color: AppTheme.textPrimary,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 8),
                TextFormField(
                  controller: _contentController,
                  maxLines: 7,
                  minLines: 4,
                  maxLength: 1000000,
                  keyboardType: TextInputType.multiline,
                  decoration: const InputDecoration(
                    hintText:
                        'Type or paste research, ideas, snippets, or notes...',
                    alignLabelWithHint: true,
                    counterText: '',
                  ),
                  validator: (val) {
                    if (val == null || val.trim().isEmpty) {
                      return 'Content cannot be empty or whitespace-only';
                    }
                    return null;
                  },
                ),
              ],

              const SizedBox(height: 28),

              // Action Buttons: Cancel and Save
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: _isSubmitting ? null : _cancel,
                      style: OutlinedButton.styleFrom(
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(
                          borderRadius: BorderRadius.circular(12),
                        ),
                        side: const BorderSide(color: AppTheme.border),
                      ),
                      child: const Text('Cancel'),
                    ),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    flex: 2,
                    child: ElevatedButton(
                      onPressed: _isSubmitting ? null : _submit,
                      child: _isSubmitting
                          ? const SizedBox(
                              width: 20,
                              height: 20,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                valueColor:
                                    AlwaysStoppedAnimation<Color>(Colors.white),
                              ),
                            )
                          : Row(
                              mainAxisAlignment: MainAxisAlignment.center,
                              children: [
                                Icon(
                                  isUrl
                                      ? Icons.cloud_download_rounded
                                      : Icons.save_rounded,
                                  size: 18,
                                ),
                                const SizedBox(width: 8),
                                Text(isUrl ? 'Ingest Web Link' : 'Save Note'),
                              ],
                            ),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TypeTab extends StatelessWidget {
  final String label;
  final IconData icon;
  final bool isSelected;
  final VoidCallback onTap;

  const _TypeTab({
    required this.label,
    required this.icon,
    required this.isSelected,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      behavior: HitTestBehavior.opaque,
      child: Container(
        padding: const EdgeInsets.symmetric(vertical: 10),
        decoration: BoxDecoration(
          color: isSelected ? AppTheme.primary : Colors.transparent,
          borderRadius: BorderRadius.circular(10),
        ),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.center,
          children: [
            Icon(
              icon,
              size: 16,
              color: isSelected ? Colors.white : AppTheme.textSecondary,
            ),
            const SizedBox(width: 6),
            Text(
              label,
              style: TextStyle(
                color: isSelected ? Colors.white : AppTheme.textSecondary,
                fontSize: 13,
                fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
              ),
            ),
          ],
        ),
      ),
    );
  }
}

