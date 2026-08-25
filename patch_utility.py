import re

def apply_patch(original_text: str, patch_text: str) -> str:
    """
    Applies a standard unified diff patch to original_text and returns the modified text.
    Handles line additions, deletions, and replacements.
    """
    if not patch_text:
        return original_text

    # Keep line endings intact
    original_lines = original_text.splitlines(keepends=True)
    
    # Ensure original_lines is not empty if original_text is empty
    if not original_lines and original_text:
        original_lines = [original_text]
        
    patch_lines = patch_text.splitlines(keepends=True)

    hunk_re = re.compile(r'^@@ -(\d+),?(\d*) \+(\d+),?(\d*) @@')

    offset = 0  # tracks line shifts from insertions/deletions
    i = 0
    while i < len(patch_lines):
        line = patch_lines[i]
        match = hunk_re.match(line)
        if match:
            old_start = int(match.group(1))
            
            # Unified diff lines are 1-indexed.
            # Convert to 0-indexed and apply current offset.
            start_idx = max(0, old_start - 1 + offset)
            
            hunk_original = []
            hunk_new = []
            
            i += 1
            while i < len(patch_lines) and not patch_lines[i].startswith('@@'):
                pline = patch_lines[i]
                if pline.startswith('+'):
                    hunk_new.append(pline[1:])
                elif pline.startswith('-'):
                    hunk_original.append(pline[1:])
                elif pline.startswith(' '):
                    hunk_original.append(pline[1:])
                    hunk_new.append(pline[1:])
                elif pline.strip() == '\\ No newline at end of file':
                    pass
                else:
                    # Treat anything else as context
                    hunk_original.append(pline)
                    hunk_new.append(pline)
                i += 1
            
            end_idx = start_idx + len(hunk_original)
            original_lines[start_idx:end_idx] = hunk_new
            
            # Update the line index offset
            offset += len(hunk_new) - len(hunk_original)
        else:
            i += 1

    return "".join(original_lines)

