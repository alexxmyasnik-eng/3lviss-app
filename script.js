// Ждем, пока вся страница загрузится
document.addEventListener('DOMContentLoaded', function() {
    
    // --- ВАЖНО! ---
    // Это адрес, где будет запущен ваш сервер. 
    // Для тестов на вашем компьютере это будет 'http://127.0.0.1:8000'.
    const API_BASE_URL = 'http://127.0.0.1:8000';

    // Получаем доступ к API Телеграма
    const tg = window.Telegram.WebApp;
    tg.ready();

    // Находим элементы на странице
    const userNameElem = document.getElementById('user-name');
    const starBalanceElem = document.getElementById('star-balance');
    const openCaseBtn = document.getElementById('open-case-btn');

    // Проверяем, что приложение открыто через Телеграм
    if (tg.initDataUnsafe?.user) {
        const user = tg.initDataUnsafe.user;
        
        // Отображаем имя пользователя
        userNameElem.innerText = user.first_name || user.username;
        
        // Запрашиваем данные (включая баланс) с нашего сервера
        fetchUserData(user);
    } else {
        document.body.innerHTML = "Пожалуйста, откройте это приложение через Telegram.";
    }

    // Функция для получения данных с нашего сервера
    async function fetchUserData(user) {
        try {
            const response = await fetch(`${API_BASE_URL}/get_user_data`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    telegram_id: user.id,
                    username: user.username,
                    first_name: user.first_name,
                }),
            });
            const data = await response.json();
            starBalanceElem.innerText = data.stars; // Обновляем баланс на странице
        } catch (error) {
            console.error('Ошибка при загрузке данных пользователя:', error);
            userNameElem.innerText = "Ошибка загрузки";
        }
    }
    
    // Добавляем обработчик на кнопку открытия кейса
    if (openCaseBtn) {
        openCaseBtn.addEventListener('click', handleOpenCase);
    }

    // Функция для открытия кейса
    async function handleOpenCase() {
        // Блокируем кнопку, чтобы избежать двойных нажатий
        openCaseBtn.disabled = true;
        
        try {
            const response = await fetch(`${API_BASE_URL}/open_case`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    telegram_id: tg.initDataUnsafe.user.id
                }),
            });
            const data = await response.json();

            if (data.error) {
                alert(data.error); // Показываем ошибку (например, "не хватает звезд")
            } else if (data.success) {
                // Сюда мы позже добавим анимацию рулетки
                alert(`Поздравляем! Вы выиграли: ${data.won_item.name}`);
                
                // Обновляем баланс на странице
                starBalanceElem.innerText = data.new_balance;
            }
        } catch (error) {
            console.error('Ошибка при открытии кейса:', error);
            alert("Сервер не отвечает. Попробуйте позже.");
        } finally {
            // Включаем кнопку обратно
            openCaseBtn.disabled = false;
        }
    }
});
