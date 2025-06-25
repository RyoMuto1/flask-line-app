// 流入経路分析ページ専用JavaScript - 完全独立（Bootstrap・jQuery依存除去済み）

// フォルダ選択
function selectFolder(folderId) {
    selectedFolderId = folderId;
    
    // アクティブ状態の更新
    document.querySelectorAll('.analytics__sidebar-item').forEach(item => {
        item.classList.remove('active');
    });
    
    const selectedItem = document.querySelector(`[data-folder-id="${folderId}"]`);
    if (selectedItem) {
        selectedItem.classList.add('active');
    }
    
    // ページリロードまたはフィルタリング（簡略化のためリロード）
    window.location.href = `/admin/line-source-analytics?folder_id=${folderId}`;
}

// モーダル閉じる
function closeModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('show');
    }
}

// フォルダドロップダウンの表示切り替え
function toggleFolderDropdown(folderId) {
    const dropdown = document.getElementById(`dropdown-${folderId}`);
    const folderDropdown = dropdown.closest('.analytics__folder-dropdown');
    
    // 他のドロップダウンを閉じる
    document.querySelectorAll('.analytics__folder-dropdown.show').forEach(el => {
        if (el !== folderDropdown) {
            el.classList.remove('show');
        }
    });
    
    // 現在のドロップダウンを切り替え
    folderDropdown.classList.toggle('show');
}

// リンクドロップダウンの表示切り替え
function toggleDropdown(linkId) {
    const dropdown = document.getElementById(`dropdown-link-${linkId}`);
    const parentDropdown = dropdown.closest('.analytics__dropdown');
    
    // 他のドロップダウンを閉じる
    document.querySelectorAll('.analytics__dropdown.show').forEach(el => {
        if (el !== parentDropdown) {
            el.classList.remove('show');
        }
    });
    
    // 現在のドロップダウンを切り替え
    parentDropdown.classList.toggle('show');
}

// フォルダ名編集
function editFolderName(folderId, currentName) {
    document.getElementById('editFolderId').value = folderId;
    document.getElementById('editFolderName').value = currentName;
    const modal = document.getElementById('editFolderModal');
    if (modal) {
        modal.style.display = 'block';
        modal.classList.add('show');
    }
    
    // ドロップダウンを閉じる
    document.querySelectorAll('.analytics__folder-dropdown.show').forEach(el => {
        el.classList.remove('show');
    });
}

// フォルダ更新
function updateFolder(event) {
    event.preventDefault();
    
    const folderId = document.getElementById('editFolderId').value;
    const newName = document.getElementById('editFolderName').value.trim();
    
    if (!newName) {
        alert('フォルダ名を入力してください');
        return;
    }
    
    const formData = new FormData();
    formData.append('name', newName);
    
    fetch(`/admin/line-source-analytics/folders/edit/${folderId}`, {
        method: 'POST',
        body: formData
    })
    .then(response => {
        if (response.ok) {
            location.reload();
        } else {
            alert('更新に失敗しました');
        }
    })
    .catch(error => {
        console.error('エラー:', error);
        alert('エラーが発生しました');
    });
}

// フォルダ削除
function deleteFolder(folderId) {
    if (!confirm('このフォルダを削除しますか？フォルダ内のリンクは未分類フォルダに移動されます。')) {
        return;
    }
    
    fetch(`/admin/line-source-analytics/folders/delete/${folderId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (response.ok) {
            location.reload();
        } else {
            alert('削除に失敗しました');
        }
    })
    .catch(error => {
        console.error('エラー:', error);
        alert('エラーが発生しました');
    });
}

// リンク削除
function deleteLink(linkId) {
    if (!confirm('このリンクを削除しますか？関連する登録情報も削除されます。')) {
        return;
    }
    
    fetch(`/admin/line-source-analytics/delete-link/${linkId}`, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        }
    })
    .then(response => {
        if (response.ok) {
            location.reload();
        } else {
            alert('削除に失敗しました');
        }
    })
    .catch(error => {
        console.error('エラー:', error);
        alert('エラーが発生しました');
    });
}

// URLをクリップボードにコピー
function copyToClipboard(text) {
    if (navigator.clipboard) {
        navigator.clipboard.writeText(text).then(() => {
            alert('URLをクリップボードにコピーしました');
        }).catch(err => {
            console.error('コピーに失敗:', err);
            fallbackCopyTextToClipboard(text);
        });
    } else {
        fallbackCopyTextToClipboard(text);
    }
}

// フォールバック用コピー機能
function fallbackCopyTextToClipboard(text) {
    const textArea = document.createElement("textarea");
    textArea.value = text;
    textArea.style.position = "fixed";
    textArea.style.left = "-999999px";
    textArea.style.top = "-999999px";
    document.body.appendChild(textArea);
    textArea.focus();
    textArea.select();
    
    try {
        const result = document.execCommand('copy');
        if (result) {
            alert('URLをクリップボードにコピーしました');
        } else {
            alert('コピーに失敗しました');
        }
    } catch (err) {
        console.error('コピーエラー:', err);
        alert('コピーに失敗しました。手動でURLをコピーしてください。');
    }
    
    document.body.removeChild(textArea);
}

// フォルダ並び替え
function reorderFolders() {
    document.getElementById('reorderTitle').textContent = 'フォルダ並び替え';
    const folders = document.querySelectorAll('.analytics__sidebar-item[data-folder-id]');
    const list = document.getElementById('reorderList');
    list.innerHTML = '';
    
    folders.forEach(folder => {
        const folderId = folder.dataset.folderId;
        const folderName = folder.querySelector('.analytics__sidebar-name').textContent;
        const item = document.createElement('div');
        item.className = 'analytics__sortable-item';
        item.dataset.id = folderId;
        item.innerHTML = `
            <i class="fas fa-grip-vertical analytics__drag-handle"></i>
            <div class="analytics__item-content">
                <i class="fas fa-folder"></i>
                <span>${folderName}</span>
            </div>
        `;
        list.appendChild(item);
    });
    
    // Sortable.js を使用（要ライブラリ読み込み）
    if (window.Sortable) {
        window.currentSortable = Sortable.create(list, {
            handle: '.analytics__drag-handle',
            animation: 150
        });
    }
    
    window.currentReorderType = 'folder';
    const modal = document.getElementById('reorderModal');
    if (modal) {
        modal.style.display = 'block';
        modal.classList.add('show');
    }
}

// リンク並び替え
function reorderLinks() {
    document.getElementById('reorderTitle').textContent = 'リンク並び替え';
    const links = document.querySelectorAll('#linkTableBody tr');
    const list = document.getElementById('reorderList');
    list.innerHTML = '';
    
    links.forEach((link, index) => {
        const linkName = link.querySelector('.analytics__link-name').textContent;
        const item = document.createElement('div');
        item.className = 'analytics__sortable-item';
        item.dataset.index = index;
        item.innerHTML = `
            <i class="fas fa-grip-vertical analytics__drag-handle"></i>
            <div class="analytics__item-content">
                <i class="fas fa-link"></i>
                <span>${linkName}</span>
            </div>
        `;
        list.appendChild(item);
    });
    
    // Sortable.js を使用（要ライブラリ読み込み）
    if (window.Sortable) {
        window.currentSortable = Sortable.create(list, {
            handle: '.analytics__drag-handle',
            animation: 150
        });
    }
    
    window.currentReorderType = 'link';
    const modal = document.getElementById('reorderModal');
    if (modal) {
        modal.style.display = 'block';
        modal.classList.add('show');
    }
}

// 順序保存
function saveOrder() {
    const items = document.querySelectorAll('#reorderList .analytics__sortable-item');
    const order = Array.from(items).map(item => 
        window.currentReorderType === 'folder' ? item.dataset.id : item.dataset.index
    );
    
    let url, data;
    if (window.currentReorderType === 'folder') {
        url = '/admin/line-source-analytics/folders/reorder';
        data = { folder_order: order };
    } else {
        url = '/admin/line-source-analytics/links/reorder';
        data = { 
            link_order: order,
            folder_id: window.analyticsSelectedFolderId || null
        };
    }
    
    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify(data)
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            location.reload();
        } else {
            alert('並び替えの保存に失敗しました');
        }
    });
    
    closeModal('reorderModal');
}

// モーダル表示関数
function showCreateFolderModal() {
    console.log('=== フォルダ作成モーダルを開く ===');
    const modal = document.getElementById('newFolderModal');
    if (modal) {
        modal.style.display = 'block';
        // CSSクラスも追加
        modal.classList.add('show');
        console.log('モーダル表示成功');
    } else {
        console.error('newFolderModalが見つかりません');
    }
}

// フォルダ作成処理
function createFolder(event) {
    console.log('=== フォルダ作成処理開始 ===');
    event.preventDefault(); // デフォルトのフォーム送信を防ぐ
    
    const formData = new FormData(event.target);
    console.log('フォーム データ:', Array.from(formData.entries()));
    
    fetch('/admin/line-source-analytics/folders/create', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        console.log('レスポンス受信:', response.status);
        return response.json();
    })
    .then(data => {
        console.log('レスポンス内容:', data);
        if (data.success) {
            closeAnalyticsModal('newFolderModal');
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

// リンク作成処理
function createLink(event) {
    console.log('=== リンク作成処理開始 ===');
    event.preventDefault(); // デフォルトのフォーム送信を防ぐ
    
    const formData = new FormData(event.target);
    console.log('リンクフォームデータ:', Array.from(formData.entries()));
    
    fetch('/admin/line-source-analytics/create-link', {
        method: 'POST',
        body: formData
    })
    .then(response => {
        console.log('リンクレスポンス受信:', response.status);
        return response.json();
    })
    .then(data => {
        console.log('リンクレスポンス内容:', data);
        if (data.success) {
            closeAnalyticsModal('createLinkModal');
            location.reload();
        } else {
            alert('リンクの作成に失敗しました: ' + data.message);
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('エラーが発生しました');
    });
}

function showCreateLinkModal() {
    console.log('=== リンク作成モーダルを開く ===');
    const modal = document.getElementById('createLinkModal');
    if (modal) {
        modal.style.display = 'block';
        // CSSクラスも追加
        modal.classList.add('show');
        console.log('リンクモーダル表示成功');
    } else {
        console.error('createLinkModalが見つかりません');
    }
}

function closeAnalyticsModal(modalId) {
    const modal = document.getElementById(modalId);
    if (modal) {
        modal.style.display = 'none';
        modal.classList.remove('show');
    }
}

// 流入経路分析システム
let selectedFolderId = window.analyticsSelectedFolderId || null;
let folderData = [];
let linkData = [];

// 初期化
document.addEventListener('DOMContentLoaded', function() {
    // 外部クリックでドロップダウンを閉じる
    document.addEventListener('click', function(event) {
        if (!event.target.closest('.analytics__folder-dropdown') && !event.target.closest('.analytics__dropdown')) {
            document.querySelectorAll('.analytics__folder-dropdown.show, .analytics__dropdown.show').forEach(el => {
                el.classList.remove('show');
            });
        }
    });
    
    // モーダル外クリックで閉じる
    document.addEventListener('click', function(event) {
        if (event.target.classList.contains('analytics__modal')) {
            event.target.style.display = 'none';
            event.target.classList.remove('show');
        }
    });
    
    // ドロップダウン外クリックで閉じる
    document.addEventListener('click', function(event) {
        if (!event.target.closest('.analytics__dropdown') && !event.target.closest('.analytics__folder-dropdown')) {
            document.querySelectorAll('.analytics__dropdown-content, .analytics__folder-dropdown-content').forEach(content => {
                content.style.display = 'none';
            });
        }
    });
}); 