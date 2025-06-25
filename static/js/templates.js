// テンプレート管理ページ専用JavaScript - 完全独立

// フォルダ選択
function selectFolder(folderId) {
    window.location.href = `/admin/templates?folder_id=${folderId}`;
}

// フォルダ作成モーダル表示
function showCreateFolderModal() {
    document.getElementById('templatesNewFolderModal').classList.add('show');
    document.getElementById('templatesNewFolderModal').style.display = 'block';
}

// フォルダ作成処理
function createFolder(event) {
    event.preventDefault(); // デフォルトのフォーム送信を防ぐ
    
    const formData = new FormData(event.target);
    
    fetch('/admin/templates/folders/create', {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            closeModal('templatesNewFolderModal');
            location.reload();
        } else {
            alert('フォルダの作成に失敗しました: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('エラーが発生しました');
    });
}

// テンプレート作成ドロップダウン表示/非表示
function toggleTemplateDropdown() {
    const dropdown = document.querySelector('.templates__dropdown');
    dropdown.classList.toggle('show');
}

// 標準メッセージ作成画面表示
function showStandardMessageModal() {
    document.querySelector('.templates__dropdown').classList.remove('show');
    
    // 選択されたフォルダIDを取得
    const selectedFolderId = window.templatesSelectedFolderId || null;
    
    // テンプレート作成ページに遷移
    let url = '/admin/templates/create';
    if (selectedFolderId && selectedFolderId !== null) {
        url += '?folder_id=' + selectedFolderId;
    }
    window.location.href = url;
}

// カルーセルメッセージ（未実装）
function showCarouselModal() {
    document.querySelector('.templates__dropdown').classList.remove('show');
    alert('カルーセルメッセージ機能は実装予定です');
}

// フレックスメッセージ（未実装）
function showFlexModal() {
    document.querySelector('.templates__dropdown').classList.remove('show');
    alert('フレックスメッセージ機能は実装予定です');
}

// テンプレートパック作成（未実装）
function showCreatePackModal() {
    alert('テンプレートパック機能は実装予定です');
}

// モーダル閉じる
function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    modal.classList.remove('show');
    modal.style.display = 'none';
}

// 全選択トグル
function toggleSelectAll() {
    const selectAll = document.getElementById('selectAll');
    const checkboxes = document.querySelectorAll('.templates__checkbox[name="template_ids"]');
    checkboxes.forEach(cb => cb.checked = selectAll.checked);
}

// フォルダドロップダウンの表示切り替え
function toggleFolderDropdown(folderId) {
    const dropdown = document.getElementById(`dropdown-${folderId}`);
    const folderDropdown = dropdown.closest('.templates__folder-dropdown');
    
    // 他のドロップダウンを閉じる
    document.querySelectorAll('.templates__folder-dropdown.show').forEach(el => {
        if (el !== folderDropdown) {
            el.classList.remove('show');
        }
    });
    
    // 現在のドロップダウンを切り替え
    folderDropdown.classList.toggle('show');
}

// フォルダ名編集
function editFolderName(folderId, currentName, currentColor) {
    document.getElementById('editFolderId').value = folderId;
    document.getElementById('editFolderName').value = currentName;
    document.getElementById('editFolderColor').value = currentColor;
    document.getElementById('editFolderModal').classList.add('show');
    document.getElementById('editFolderModal').style.display = 'block';
    
    // ドロップダウンを閉じる
    document.querySelectorAll('.templates__folder-dropdown.show').forEach(el => {
        el.classList.remove('show');
    });
}

// フォルダ更新
function updateFolder(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    const folderId = formData.get('folder_id');
    
    fetch(`/admin/templates/folders/edit/${folderId}`, {
        method: 'POST',
        body: formData
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('フォルダの更新に失敗しました: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('エラーが発生しました');
    });
}

// フォルダ削除
function deleteFolder(folderId) {
    if (confirm('このフォルダを削除しますか？\n※フォルダ内にテンプレートがある場合は削除できません。')) {
        fetch(`/admin/templates/folders/delete/${folderId}`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            }
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert('フォルダの削除に失敗しました: ' + data.message);
            }
        });
    }
    
    // ドロップダウンを閉じる
    document.querySelectorAll('.templates__folder-dropdown.show').forEach(el => {
        el.classList.remove('show');
    });
}

// テンプレート削除
function deleteTemplate(templateId) {
    if (confirm('このテンプレートを削除しますか？')) {
        fetch('/admin/templates/delete', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({template_id: templateId})
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert('削除に失敗しました: ' + data.message);
            }
        });
    }
}

// 選択済みテンプレート削除
function deleteSelectedTemplates() {
    const selectedIds = Array.from(document.querySelectorAll('.templates__checkbox[name="template_ids"]:checked'))
                           .map(cb => cb.value);
    
    if (selectedIds.length === 0) {
        alert('削除するテンプレートを選択してください');
        return;
    }
    
    if (confirm(`選択した${selectedIds.length}個のテンプレートを削除しますか？`)) {
        fetch('/admin/templates/delete-multiple', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({template_ids: selectedIds})
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                location.reload();
            } else {
                alert('削除に失敗しました: ' + data.message);
            }
        });
    }
}

// テンプレート操作ドロップダウン
function toggleTemplateOperationDropdown(templateId) {
    const dropdown = document.getElementById(`operationDropdown-${templateId}`);
    const templateDropdown = dropdown.closest('.templates__dropdown');
    
    // 他のドロップダウンを閉じる
    document.querySelectorAll('.templates__dropdown.show').forEach(el => {
        if (el !== templateDropdown) {
            el.classList.remove('show');
        }
    });
    
    // 現在のドロップダウンを切り替え
    templateDropdown.classList.toggle('show');
}

// テンプレート名編集
function editTemplateName(templateId, currentName) {
    document.getElementById('editTemplateId').value = templateId;
    document.getElementById('editTemplateNameInput').value = currentName;
    document.getElementById('editTemplateNameModal').classList.add('show');
    document.getElementById('editTemplateNameModal').style.display = 'block';
    
    // ドロップダウンを閉じる
    document.querySelectorAll('.templates__dropdown.show').forEach(el => {
        el.classList.remove('show');
    });
}

// テンプレート名更新
function updateTemplateName(event) {
    event.preventDefault();
    const formData = new FormData(event.target);
    
    fetch('/admin/templates/edit-name', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            template_id: formData.get('template_id'),
            name: formData.get('name')
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('テンプレート名の更新に失敗しました: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('エラーが発生しました');
    });
}

// テンプレート編集ページへリダイレクト
function editTemplateRedirect(templateId) {
    window.location.href = `/admin/templates/edit/${templateId}`;
}

// プレビュー・テスト送信モーダル
function showPreviewTestModal(templateId) {
    // テンプレート詳細を取得してプレビューを表示
    fetch(`/admin/templates/preview/${templateId}`)
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            // プレビューコンテンツを設定
            const previewContent = document.getElementById('previewTestContent');
            if (data.template.type === 'text') {
                previewContent.innerHTML = data.template.content.replace(/\n/g, '<br>');
            } else if (data.template.type === 'image') {
                const imageUrl = data.template.image_url || data.template.content;
                previewContent.innerHTML = `<div class="image-message"><img src="${imageUrl}" alt="プレビュー画像" style="max-width: 100%; height: auto;"></div>`;
            } else {
                previewContent.innerHTML = data.template.preview_text || 'プレビューできません';
            }
            
            // モーダル表示
            document.getElementById('previewTestModal').classList.add('show');
            document.getElementById('previewTestModal').style.display = 'block';
            
            // テンプレートIDを保存
            window.currentTemplateId = templateId;
        } else {
            alert('プレビューの取得に失敗しました: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('エラーが発生しました');
    });
}

// 検索機能（簡易実装）
function searchTemplates() {
    const searchTerm = document.getElementById('searchBox').value.toLowerCase();
    const rows = document.querySelectorAll('#templateTableBody tr');
    
    rows.forEach(row => {
        const templateName = row.querySelector('.templates__template-title').textContent.toLowerCase();
        const templatePreview = row.querySelector('.templates__template-preview');
        const previewText = templatePreview ? templatePreview.textContent.toLowerCase() : '';
        
        if (templateName.includes(searchTerm) || previewText.includes(searchTerm)) {
            row.style.display = '';
        } else {
            row.style.display = 'none';
        }
    });
}

// テストユーザー関連機能（簡易実装）
function searchUsers(query) {
    // 実装予定：ユーザー検索API呼び出し
    console.log('ユーザー検索:', query);
}

function showSearchSuggestions() {
    // 実装予定：検索候補表示
}

function hideSearchSuggestions() {
    // 実装予定：検索候補非表示
}

function debugTestUsers() {
    console.log('テストユーザーデバッグ情報');
}

function clearTestUsers() {
    document.getElementById('selectedTestUsers').innerHTML = `
        <div class="templates__no-users-message">
            テストユーザーが登録されていません。<br>
            上の検索欄から友だちを検索して追加してください。
        </div>
    `;
}

// 並び替え機能（簡易実装）
function reorderFolders() {
    alert('フォルダ並び替え機能は実装予定です');
}

function reorderTemplates() {
    alert('テンプレート並び替え機能は実装予定です');
}

// 初期化とイベントリスナー
document.addEventListener('DOMContentLoaded', function() {
    // 外部クリックでドロップダウンを閉じる
    document.addEventListener('click', function(event) {
        if (!event.target.closest('.templates__dropdown')) {
            document.querySelectorAll('.templates__dropdown.show').forEach(el => {
                el.classList.remove('show');
            });
        }
        if (!event.target.closest('.templates__folder-dropdown')) {
            document.querySelectorAll('.templates__folder-dropdown.show').forEach(el => {
                el.classList.remove('show');
            });
        }
    });
}); 