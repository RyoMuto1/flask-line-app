// タグ管理ページ専用JavaScript - 完全独立（jQuery依存除去済み）

// タグデータを格納するグローバル変数
let tagData = [];

// モーダル表示関数
function showCreateFolderModal() {
    document.getElementById('tagsCreateFolderModal').style.display = 'block';
}

function showCreateTagModal() {
    document.getElementById('tagsCreateTagModal').style.display = 'block';
}

function showImportModal() {
    document.getElementById('tagsImportModal').style.display = 'block';
}

function closeTagModal(modalId) {
    document.getElementById(modalId).style.display = 'none';
}

// タグ管理システムオブジェクト
const TagsManager = (function() {
    
    // 初期化
    function init() {
        console.log('タグ管理システムを初期化中...');
        
        // サーバーからタグデータを取得
        fetch('/admin/api/all-tags')
            .then(response => response.json())
            .then(data => {
                if (data.success) {
                    tagData = data.tags || [];
                    console.log('タグデータ取得成功:', tagData.length + '件');
                    renderFolderList();
                    
                    // デフォルトで最初のフォルダを選択
                    const firstFolder = tagData.find(t => t.is_folder === 1);
                    if (firstFolder) {
                        renderFolderContent(firstFolder.id);
                    }
                } else {
                    console.error('タグデータ取得失敗:', data.error);
                }
            })
            .catch(error => {
                console.error('タグデータ取得エラー:', error);
            });
        
        // フォームイベントリスナーを設定
        setupFormListeners();
    }
    
    // フォームイベントリスナーの設定
    function setupFormListeners() {
        // フォルダ作成フォーム
        const folderForm = document.getElementById('tags__createFolderForm');
        if (folderForm) {
            folderForm.addEventListener('submit', function(e) {
                e.preventDefault();
                handleCreateFolder();
            });
        }
        
        // タグ作成フォーム
        const tagForm = document.getElementById('tags__createTagForm');
        if (tagForm) {
            tagForm.addEventListener('submit', function(e) {
                e.preventDefault();
                handleCreateTag();
            });
        }
        
        // インポートフォーム
        const importForm = document.getElementById('tags__importForm');
        if (importForm) {
            importForm.addEventListener('submit', function(e) {
                e.preventDefault();
                handleImportTags();
            });
        }
        
        // タグ編集フォーム
        const editForm = document.getElementById('tags__editForm');
        if (editForm) {
            editForm.addEventListener('submit', function(e) {
                e.preventDefault();
                handleEditTag();
            });
        }
    }
    
    // フォルダ作成ハンドラ
    function handleCreateFolder() {
        console.log('=== フォルダ作成関数が呼ばれました ===');
        const name = document.getElementById('tags__folderName').value.trim();
        console.log('入力されたフォルダ名:', name);
        
        if (!name) {
            document.getElementById('tags__createFolderError').textContent = 'フォルダ名を入力してください';
            return;
        }
        
        console.log('フォルダ作成APIを呼び出します: /admin/tags/folders/create');
        fetch('/admin/tags/folders/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `name=${encodeURIComponent(name)}`
        })
        .then(response => {
            console.log('レスポンス受信:', response.status);
            return response.json();
        })
        .then(res => {
            console.log('レスポンス内容:', res);
            if (res.success) {
                closeTagModal('tagsCreateFolderModal');
                location.reload();
            } else {
                document.getElementById('tags__createFolderError').textContent = res.error || 'フォルダの作成に失敗しました';
            }
        })
        .catch(error => {
            console.error('エラー発生:', error);
            document.getElementById('tags__createFolderError').textContent = 'エラーが発生しました';
        });
    }
    
    // タグ作成ハンドラ
    function handleCreateTag() {
        const name = document.getElementById('tags__tagName').value.trim();
        const folderId = document.getElementById('tags__parentTag').value;
        
        if (!name) {
            document.getElementById('tags__createTagError').textContent = 'タグ名を入力してください';
            return;
        }
        
        const body = `name=${encodeURIComponent(name)}&folder_id=${folderId || ''}`;
        
        fetch('/admin/tags/create', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: body
        })
        .then(response => response.json())
        .then(res => {
            if (res.success) {
                location.reload();
            } else {
                document.getElementById('tags__createTagError').textContent = res.error || 'タグの作成に失敗しました';
            }
        })
        .catch(error => {
            document.getElementById('tags__createTagError').textContent = 'エラーが発生しました';
        });
    }
    
    // タグ編集ハンドラ
    function handleEditTag() {
        const tagId = document.getElementById('tags__editTagId').value;
        const name = document.getElementById('tags__editTagName').value.trim();
        
        if (!name) {
            document.getElementById('tags__editError').textContent = 'タグ名を入力してください';
            return;
        }
        
        fetch('/admin/tags/edit/' + tagId, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: `name=${encodeURIComponent(name)}`
        })
        .then(response => response.json())
        .then(res => {
            if (res.success) {
                location.reload();
            } else {
                document.getElementById('tags__editError').textContent = res.error || 'タグの更新に失敗しました';
            }
        })
        .catch(error => {
            document.getElementById('tags__editError').textContent = 'エラーが発生しました';
        });
    }
    
    // CSVインポートハンドラ
    function handleImportTags() {
        const fileInput = document.getElementById('tags__csvFile');
        if (!fileInput.files.length) {
            document.getElementById('tags__importError').textContent = 'CSVファイルを選択してください';
            return;
        }
        
        const formData = new FormData();
        formData.append('csv_file', fileInput.files[0]);
        
        fetch('/admin/tags/import', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(res => {
            if (res.success) {
                alert(res.message || 'インポートが完了しました');
                location.reload();
            } else {
                document.getElementById('tags__importError').textContent = res.error || 'インポートに失敗しました';
            }
        })
        .catch(error => {
            document.getElementById('tags__importError').textContent = 'エラーが発生しました';
        });
    }
    
    // フォルダリストの描画
    function renderFolderList() {
        // フォルダ一覧を取得（is_folder=1のもの）
        const folders = tagData.filter(t => t.is_folder === 1);
        
        let html = '';
        
        // フォルダーを表示
        folders.forEach(folder => {
            const folderTags = getTagsInFolder(folder.id);
            html += '<li class="tags__sidebar-item tags__folder-item" data-id="' + folder.id + '" onclick="TagsManager.selectFolder(' + folder.id + ')">';
            html += '<i class="fas fa-folder tags__sidebar-icon" style="color: ' + (folder.color || '#FFA500') + '"></i>';
            html += '<span class="tags__sidebar-name">' + folder.name + '</span>';
            html += '<span class="tags__sidebar-count">(' + folderTags.length + ')</span>';
            html += '</li>';
        });
        
        const folderList = document.getElementById('tags__folderList');
        if (folderList) {
            folderList.innerHTML = html;
        }
    }
    
    // 指定されたフォルダに属するタグを取得
    function getTagsInFolder(folderId) {
        return tagData.filter(t => t.folder_id == folderId && t.is_folder !== 1);
    }
    
    // 指定したタグがフォルダかどうか判定
    function isFolder(tagId) {
        const tag = tagData.find(t => t.id == tagId);
        return tag && tag.is_folder === 1;
    }
    
    // フォルダが選択されたときの表示
    function renderFolderContent(folderId) {
        // アクティブ状態の更新
        document.querySelectorAll('.tags__folder-item').forEach(el => el.classList.remove('active'));
        const activeItem = document.querySelector('[data-id="' + folderId + '"]');
        if (activeItem) {
            activeItem.classList.add('active');
        }
        
        // 表示するタグを取得
        const tagsToShow = getTagsInFolder(folderId);
        
        // タグリスト表示
        let html = '';
        if (tagsToShow.length > 0) {
            tagsToShow.forEach((tag) => {
                html += '<tr>';
                html += '<td><input type="checkbox" class="tags__tag-checkbox" value="' + tag.id + '"></td>';
                html += '<td><div class="tags__tag-item"><span class="tags__tag-name">' + tag.name + '</span></div></td>';
                html += '<td><span class="tags__user-count">' + (tag.user_count || 0) + '人</span></td>';
                html += '<td><span class="tags__item-date">' + formatDate(tag.created_at) + '</span></td>';
                html += '<td><button class="tags__action-btn" onclick="TagsManager.editTag(' + tag.id + ', \'' + tag.name + '\')">編集</button></td>';
                html += '</tr>';
            });
        } else {
            html = '<tr><td colspan="5" style="text-align: center; padding: 1rem;">このフォルダにはタグがありません</td></tr>';
        }
        
        const listContainer = document.getElementById('tags__listContainer');
        if (listContainer) {
            listContainer.innerHTML = html;
        }
    }
    
    // 日付フォーマット
    function formatDate(dateStr) {
        if (!dateStr) return '';
        const date = new Date(dateStr);
        return date.getFullYear() + '.' + 
               (date.getMonth() + 1).toString().padStart(2, '0') + '.' + 
               date.getDate().toString().padStart(2, '0');
    }
    
    // パブリックメソッド
    return {
        init: init,
        
        // フォルダ選択
        selectFolder: function(folderId) {
            renderFolderContent(folderId);
        },
        
        // タグ編集
        editTag: function(tagId, currentName) {
            document.getElementById('tags__editTagId').value = tagId;
            document.getElementById('tags__editTagName').value = currentName;
            document.getElementById('tags__editError').textContent = '';
            document.getElementById('tagsEditModal').style.display = 'block';
        },
        
        // 選択したタグを削除
        deleteSelectedTags: function() {
            const selectedIds = [];
            document.querySelectorAll('.tags__tag-checkbox:checked').forEach(checkbox => {
                selectedIds.push(checkbox.value);
            });
            
            if (selectedIds.length === 0) {
                alert('削除するタグを選択してください');
                return;
            }
            
            if (!confirm(selectedIds.length + '個のタグを削除しますか？')) {
                return;
            }
            
            fetch('/admin/tags/delete-multiple', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/x-www-form-urlencoded',
                },
                body: 'tag_ids=' + selectedIds.join('&tag_ids=')
            })
            .then(response => response.json())
            .then(res => {
                if (res.success) {
                    alert(res.message || '削除が完了しました');
                    location.reload();
                } else {
                    alert(res.error || '削除に失敗しました');
                }
            })
            .catch(error => {
                console.error('Error:', error);
                alert('エラーが発生しました');
            });
        }
    };
})();

// 初期化
document.addEventListener('DOMContentLoaded', function() {
    TagsManager.init();
    
    // モーダル外クリックで閉じる
    document.addEventListener('click', function(event) {
        if (event.target.classList.contains('tags__modal')) {
            event.target.style.display = 'none';
        }
    });
}); 