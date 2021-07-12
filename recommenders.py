import pandas as pd
import numpy as np

# Для работы с матрицами
from scipy.sparse import csr_matrix

# Матричная факторизация
from implicit.als import AlternatingLeastSquares
from implicit.bpr import BayesianPersonalizedRanking
from implicit.nearest_neighbours import ItemItemRecommender, CosineRecommender, TFIDFRecommender
from implicit.nearest_neighbours import bm25_weight, tfidf_weight
from metrics import precision_at_k, recall_at_k


class MainRecommender:
    """Рекоммендации, которые можно получить из ALS
    Input
    -----
    user_item_matrix: pd.DataFrame
    """

    def __init__(self, data: pd.DataFrame, weighting: str = 'bm25', model_type: str = 'als',
                 own_recommender_type: str = 'item-item'):
        """
        Input
        -----
        data: датафрейм с данными
        weighting: 'bm25', 'tfidf' - меотд взвешивания user_item_matrix
        """

        # Топ покупок каждого юзера
        self.top_purchases = data.groupby(['user_id', 'item_id'])['quantity'].count().reset_index()
        self.top_purchases.sort_values('quantity', ascending=False, inplace=True)
        self.top_purchases = self.top_purchases[self.top_purchases['item_id'] != 999999]

        # Топ покупок по всему датасету
        self.overall_top_purchases = data.groupby('item_id')['quantity'].count().reset_index()
        self.overall_top_purchases.sort_values('quantity', ascending=False, inplace=True)
        self.overall_top_purchases = self.overall_top_purchases[self.overall_top_purchases['item_id'] != 999999]
        self.overall_top_purchases = self.overall_top_purchases.item_id.tolist()

        self.user_item_matrix = self._prepare_matrix(data)  # pd.DataFrame
        self.id_to_itemid, self.id_to_userid, \
        self.itemid_to_id, self.userid_to_id = self._prepare_dicts(self.user_item_matrix)

        # Взвешивание
        if weighting == 'bm25':
            self.user_item_matrix = bm25_weight(self.user_item_matrix.T).T
        elif weighting == 'tfidf':
            self.user_item_matrix = tfidf_weight(self.user_item_matrix.T).T

        self.model = self.fit(self.user_item_matrix, model_type)
        self.own_recommender = self.fit_own_recommender(self.user_item_matrix, own_recommender_type)

    @staticmethod
    def _prepare_matrix(data: pd.DataFrame):
        """Готовит user-item матрицу"""
        user_item_matrix = pd.pivot_table(data,
                                          index='user_id',
                                          columns='item_id',
                                          values='quantity',  # Можно пробовать другие варианты
                                          aggfunc='count',
                                          fill_value=0
                                          )

        user_item_matrix = user_item_matrix.astype(float)  # необходимый тип матрицы для implicit

        return user_item_matrix

    @staticmethod
    def _prepare_dicts(user_item_matrix):
        """Подготавливает вспомогательные словари"""

        userids = user_item_matrix.index.values
        itemids = user_item_matrix.columns.values

        matrix_userids = np.arange(len(userids))
        matrix_itemids = np.arange(len(itemids))

        id_to_itemid = dict(zip(matrix_itemids, itemids))
        id_to_userid = dict(zip(matrix_userids, userids))

        itemid_to_id = dict(zip(itemids, matrix_itemids))
        userid_to_id = dict(zip(userids, matrix_userids))

        return id_to_itemid, id_to_userid, itemid_to_id, userid_to_id

    @staticmethod
    def fit_own_recommender(user_item_matrix, own_recommender_type, params=None):
        """
        Обучает модель, которая рекомендует товары, среди товаров, купленных юзером
        Параметры для рекомендательной модели передаются в виде словаря
        """

        if not params:
            params = {'K': 1, 'num_threads': 4}

        if own_recommender_type == 'item-item':
            own_recommender = ItemItemRecommender(**params)
        elif own_recommender_type == 'cosine':
            own_recommender = CosineRecommender(**params)
        elif own_recommender_type == 'tfidf':
            own_recommender = TFIDFRecommender(**params)

        own_recommender.fit(csr_matrix(user_item_matrix).T.tocsr())
        return own_recommender

    @staticmethod
    def fit(user_item_matrix, model_type, params=None):
        """
        Обучает модель
        Параметры для рекомендательной модели передаются в виде словаря
        """

        if not params:
            params = {'factors': 20, 'regularization': 0.001, 'iterations': 15, 'num_threads': 4}

        if model_type == 'als':
            model = AlternatingLeastSquares(**params)
        elif model_type == 'bpr':
            model = BayesianPersonalizedRanking(factors=n_factors,
                                                regularization=regularization,
                                                iterations=iterations,
                                                num_threads=num_threads)

        model.fit(csr_matrix(user_item_matrix).T.tocsr())
        return model

    def _update_dict(self, user_id):
        """Если появился новыю user / item, то нужно обновить словари"""

        if user_id not in self.userid_to_id.keys():
            max_id = max(list(self.userid_to_id.values()))
            max_id += 1

            self.userid_to_id.update({user_id: max_id})
            self.id_to_userid.update({max_id: user_id})

    def _get_similar_item(self, item_id):
        """Находит товар, похожий на item_id"""
        recs = self.model.similar_items(self.itemid_to_id[item_id], N=2)  # Товар похож на себя -> рекомендуем 2 товара
        top_rec = recs[1][0]  # И берем второй (не товар из аргумента метода)
        return self.id_to_itemid[top_rec]

    def _extend_with_top_popular(self, recommendations, N=5):
        """Если кол-во рекоммендаций < N, то дополняем их топ-популярными"""

        if len(recommendations) < N:
            recommendations.extend(self.overall_top_purchases[:N])
            recommendations = recommendations[:N]

        return recommendations

    def _get_recommendations(self, user, model, N=5):
        """Рекомендации через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        res = [self.id_to_itemid[rec[0]] for rec in model.recommend(userid=self.userid_to_id[user],
                                                                    user_items=csr_matrix(
                                                                        self.user_item_matrix).tocsr(),
                                                                    N=N,
                                                                    filter_already_liked_items=False,
                                                                    filter_items=[self.itemid_to_id[999999]],
                                                                    recalculate_user=False)]

        res = self._extend_with_top_popular(res, N=N)

        assert len(res) == N, 'Количество рекомендаций != {}'.format(N)
        return res

    def get_recommendations(self, user, N=5):
        """Рекомендации через стардартные библиотеки implicit"""

        self._update_dict(user_id=user)
        return self._get_recommendations(user, model=self.model, N=N)

    def get_own_recommendations(self, user, N=5):
        """Рекомендуем товары среди тех, которые юзер уже купил"""

        self._update_dict(user_id=user)
        return self._get_recommendations(user, model=self.own_recommender, N=N)

    def get_similar_items_recommendation(self, user_id, N=5):
        """Рекомендуем товары, похожие на топ-N купленных юзером товаров"""

        top_users_purchases = self.top_purchases[self.top_purchases['user_id'] == user_id].head(N)

        res = top_users_purchases['item_id'].apply(lambda x: self._get_similar_item(x)).tolist()
        res = self._extend_with_top_popular(res, N=N)

        assert len(res) == N, 'Количество рекомендаций != {}'.format(N)
        return res

    def get_similar_users_recommendation(self, user_id, N=5):
        """Рекомендуем топ-N товаров, среди купленных похожими юзерами"""

        res = []

        # Находим топ-N похожих пользователей
        similar_users = self.model.similar_users(self.userid_to_id[user_id], N=N + 1)
        similar_users = [self.id_to_userid[rec[0]] for rec in similar_users]
        similar_users = similar_users[1:]  # удалим юзера из запроса

        for _user_id in similar_users:
            res.extend(self.get_own_recommendations(_user_id, N=1))

        res = self._extend_with_top_popular(res, N=N)

        assert len(res) == N, 'Количество рекомендаций != {}'.format(N)
        return res

    @staticmethod
    def _get_result_matcher(df_result):
        result_eval_matcher = df_result.groupby('user_id')['item_id'].unique().reset_index()
        result_eval_matcher.columns = ['user_id', 'actual']
        return result_eval_matcher

    def evalMetrics(self, metric_type, df_result, target_col_name, recommend_model_type, N_PREDICT):
        """
        recommend_model_type:
            'own': self.get_own_recommendations
            'rec': self.get_recommendations
            'itm': self.get_similar_items_recommendation
            'usr': self.get_similar_users_recommendation
        """

        result_eval_matcher = self._get_result_matcher(df_result)
        result_col_name = 'result_' + recommend_model_type

        if recommend_model_type == 'own':
            result_eval_matcher[result_col_name] = result_eval_matcher[target_col_name].apply(
                lambda x: self.get_own_recommendations(x, N=N_PREDICT))
        elif recommend_model_type == 'rec':
            result_eval_matcher[result_col_name] = result_eval_matcher[target_col_name].apply(
                lambda x: self.get_recommendations(x, N=N_PREDICT))
        elif recommend_model_type == 'itm':
            result_eval_matcher[result_col_name] = result_eval_matcher[target_col_name].apply(
                lambda x: self.get_similar_items_recommendation(x, N=N_PREDICT))
        elif recommend_model_type == 'usr':
            result_eval_matcher[result_col_name] = result_eval_matcher[target_col_name].apply(
                lambda x: self.get_similar_users_recommendation(x, N=N_PREDICT))
        else:
            return 'recommend_model_type must not be empty!'

        if metric_type == 'recall':
            return result_eval_matcher.apply(lambda row: recall_at_k(row[result_col_name], row['actual'], k=N_PREDICT),
                                             axis=1).mean()
        elif metric_type == 'precision':
            return result_eval_matcher.apply(lambda row: precision_at_k(row[result_col_name], row['actual'],
                                                                        k=N_PREDICT), axis=1).mean()
        else:
            return 'recommend_model_type must not be empty!'
