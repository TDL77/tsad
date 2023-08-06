from .base import Task, TaskResult


import numpy as np
import pandas as pd
import torch
from torch import nn
import matplotlib.pyplot as plt
import pickle
from IPython import display


from .eda import HighLevelDatasetAnalysisResult


class ResidualAnomalyDetectionResult(TaskResult):

    def show(self) -> None:

        pass


# class TrainTestSplitTask(Task):

#     def __init__(self, 
#                  name: str | None = None, 
#                  **kwargs,
#                  ):
#         super().__init__(name)   
#         self.kwargs=kwargs    
        
#     def fit(self, dfs: pd.DataFrame) -> tuple[pd.DataFrame, TrainTestSplitResult]:
#         result = TrainTestSplitResult()
#         from ..utils.TrainTestSplitting import ts_train_test_split_dfs 
#         dfs = ts_train_test_split_dfs(dfs,**self.kwargs)
#         return dfs, result

#     def predict(self, df: pd.DataFrame, result: TrainTestSplitResult) -> tuple[pd.DataFrame, TrainTestSplitResult]:
#         from ..utils.TrainTestSplitting import ts_train_test_split_dfs 
#         dfs = ts_train_test_split_dfs(dfs,**self.kwargs)
#         return dfs, result


class ResidualAnomalyDetectionTask(Task):
    """        
    Pipeline Time Series Anomaly Detection based on 
    SOTA deep learning forecasting algorithms.
    
    Данный пайплайн избавит вас от проблем написания кода для: \n
    1) формирование выборок для подачи в sequence модели \n
    2) обучения моделей \n
    3) поиска аномалий в невязках \n
    
    Данный пайплайн позволяет: \n
    1) пронгозировать временные ряды, в том числе многомерные. \n
    2) вычислять невязку между прогнозом и настоящими значениями \n
    3) анализировать невязку, и возращать разметку аномалиями \n
    
    Parameters
    ----------
    preproc : object, default = sklearn.preprocessing.MinMaxScaler()
        Объект предобратки значений временного ряда.
        Требования к классу по методами атрибутам одинаковы с default.
    
    generate_res_func : func, default = generate_residuals.abs
        Функция генерация невязки. На вход y_pred, y_true. В default это
        абсолютная разница значений. Требования к функциям описаны в 
        generate_residuals.py. 
        
    res_analys_alg : object, default=stastics.Hotelling().
        Объект поиска аномалий в остатках. В default это
        статистика Хоттелинга.Требования к классам описаны в 
        generate_residuals.py. 
        
    
    Attributes
    ----------
    
    
    Return 
    ----------
    object : object Объект этого класса DL_AD

    References
    ----------
    
    Links to the papers 

    Examples
    --------
    https://github.com/waico/tsad/tree/main/examples 
    """


    def __init__(self,
                 name: str | None = None,
                 preproc=None,
                 generate_res_func=None,
                 res_analys_alg=None,
                 Loader = None
                 ):
        super().__init__(name) 

        if preproc is None:
            from sklearn.preprocessing import MinMaxScaler
            self.preproc = MinMaxScaler()

        if generate_res_func is None:
            from ..utils.ResidualAnomalyDetectionUtils.generateResidual import absoluteResidual
            self.generate_res_func = absoluteResidual

        if res_analys_alg is None:
            from ..utils.ResidualAnomalyDetectionUtils.stastics import Hotelling
            self.res_analys_alg = Hotelling()

        if Loader is None:
            from ..utils.iterators import Loader
        self.Loader = Loader

        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")





    def _get_anomaly_timestamps(self,dfs):
        """
        Вспомогательная функция для  генерации всего

        """
        X, _, y_true, _ = dfs

        all_data_iterator = self.Loader(X, y_true, self.batch_size, shuffle=False)
        y_pred = self.model.run_epoch( all_data_iterator,     
                                None, None, phase='forecast', points_ahead=self.points_ahead,
                                      device=self.device)
        residuals = self.generate_res_func(y_pred, np.array(y_true))
        point_ahead_for_residuals = 0  # мы иногда прогнозим на 10 точек вперед, ну интересует все равно на одну точку впреред
        res_indices = [y_true[i].index[point_ahead_for_residuals] for i in range(len(y_true))]
        df_residuals = pd.DataFrame(residuals[:, point_ahead_for_residuals, :], columns=self.columns,
                                    index=res_indices).sort_index()
        return df_residuals

    # -----------------------------------------------------------------------------------------
    #     Формирование сутевой части класса
    # -----------------------------------------------------------------------------------------


    def fit(self,
            dfs,
            result_base_eda: HighLevelDatasetAnalysisResult,
            model=None,
            encod_decode_model=False,
            # ужас, нужно это править, особенность encod_decode модели. Попытаться вообще еубрать эту переменную
            criterion=None,
            optimiser=None,
            batch_size=64,
            len_seq=10,
            points_ahead=5,
            n_epochs=100,
            gap=0,
            shag=1,
            intersection=True,
            test_size=0.2,
            train_size=None,
            random_state=None,
            shuffle=False,
            show_progress=True,
            show_figures=True,
            best_model_file='./best_model.pt',
            stratify=None,
            ):

        """
        Обучение модели как для задачи прогнозирования так и для задачи anomaly
        detection на имеющихся данных. fit = fit_predict_anmaloy 
        
        Parameters
        ----------
        dfs : {{df*,ts*}, list of {df*,ts*}}
            df*,ts* are pd.core.series.Seriesor or pd.core.frame.DataFrame data type.
            Исходные данные. Данные не долнжны содержать np.nan вовсе, иметь постоянную 
            и одинковую частоту of df.index и при этом не иметь пропусков. Проблему с 
            пропуском решают дробление одно df на list of df.             
        
        model : object of torch.nn.Module class, default=models.SimpleLSTM()
            Используемая модель нейронной сети. 
        
        criterion : object of torch.nn class, default=nn.MSELoss()
            Критерий подсчета ошибки для оптмизации. 
        
        optimiser : tuple = (torch.optim class ,default = torch.optim.Adam,
            dict  (dict of arguments without params models) , default=default)
            Example of optimiser : optimiser=(torch.optim.Adam,{'lr':0.001})
            Метод оптимизации нейронной сети и его параметры, указанные в 
            документации к torch.
            
        batch_size :  int, default=64
            Размер батча (Число сэмплов по которым усредняется градиент)
        
        len_seq : int, default=10
            Размер окна (количество последовательных точек ряда), на котором
            модель реально работает. По сути аналог порядка в авторегрессии. 
        
        points_ahead : int, default=5
            Горизонт прогнозирования. 
        
        n_epochs :  int, default=100 
            Количество эпох.
        
        >>> train_test_split vars
        
            gap :  int, default=0
                Сколько точек между трейном и тестом. Условно говоря,
                если крайняя точка train а это t, то первая точка теста t + gap +1.
                Параметр создан, чтобы можно было прогнозировать одну точку через большой 
                дополнительный интервал времени. 
            
            shag :  int, default=1.
                Шаг генерации выборки. Если первая точка была t у 1-ого сэмпла трейна,
                то у 2-ого сэмла трейна она будет t + shag, если intersection=True, иначе 
                тоже самое но без пересечений значений ряда. 
        
            intersection :  bool, default=True
                Наличие значений ряда (одного момента времени) в различных сэмплах выборки. 
            
            test_size : float or int, default=None
                If float, should be between 0.0 and 1.0 and represent the proportion
                of the dataset to include in the test split. If int, represents the
                absolute number of test samples. If None, the value is set to the
                complement of the train size. If ``train_size`` is also None, it will
                be set to 0.25. *
                *https://github.com/scikit-learn/scikit-learn/blob/95119c13a/sklearn/model_selection/_split.py#L2076 
                Может быть 0, тогда вернет значения X,y
            
            train_size : float or int, default=None
                If float, should be between 0.0 and 1.0 and represent the
                proportion of the dataset to include in the train split. If
                int, represents the absolute number of train samples. If None,
                the value is automatically set to the complement of the test size. *
                *https://github.com/scikit-learn/scikit-learn/blob/95119c13a/sklearn/model_selection/_split.py#L2076
            
            random_state : int, RandomState instance or None, default=None
                Controls the shuffling applied to the data before applying the split.
                Pass an int for reproducible output across multiple function calls.
                See :term:`Glossary <random_state>`.*
                *https://github.com/scikit-learn/scikit-learn/blob/95119c13a/sklearn/model_selection/_split.py#L2076
                
            
            shuffle : bool, default=True
                Whether or not to shuffle the data before splitting. If shuffle=False
                then stratify must be None. *
            
            show_progress : bool, default=True
                Показывать или нет прогресс обучения с детализацией по эпохам. 

            
            show_figures : bool, default=True
                Показывать или нет результаты решения задачии anomaly detection 
                и кривую трейна и валидации по эпохам. 
            
            
            best_model_file : string, './best_model.pt'
                Путь до файла, где будет хранится лучшие веса модели
            
            Loader : class, default=ufesul.iterators.Loader.
                Тип загрузчика, которую будет использовать как итератор в будущем, 
                благодаря которому, есть возможность бить на бачи.
        
        Attributes
        ----------

        Return 
        ----------
        list of pd.datetime anomalies on initial dataset
        """
        self.points_ahead = points_ahead
        self.len_seq = len_seq
        self.batch_size = batch_size
        self.best_model_file = best_model_file
        self.encod_decode_model = encod_decode_model
        self.columns = result_base_eda.columns
        if show_progress:
            show_progress_text = ""

        # -----------------------------------------------------------------------------------------
        #     Формирование train_iterator и val_iteraror
        # -----------------------------------------------------------------------------------------

        X_train, X_test, y_train, y_test = dfs

        train_iterator = self.Loader(X_train, y_train, batch_size, shuffle=shuffle)
        val_iterator = self.Loader(X_test, y_test, batch_size, shuffle=shuffle)

        # -----------------------------------------------------------------------------------------
        #     Обучение моделей
        # -----------------------------------------------------------------------------------------

        

        if criterion is None:
            criterion = nn.MSELoss()

        if model is None:
            from ..utils.MLmodels.DeepLearningRegressors import SimpleLSTM
            model = SimpleLSTM(len(self.columns), len(self.columns), seed=random_state)
        self.model = model

        if optimiser is None:
            optimiser = torch.optim.Adam
            optimiser = optimiser(self.model.parameters())
        else:
            args = optimiser[1]
            args['params'] = self.model.parameters()
            optimiser = optimiser[0](**args)

        history_train = []
        history_val = []
        best_val_loss = float('+inf')
        for epoch in range(n_epochs):
            train_loss = self.model.run_epoch(train_iterator, optimiser, criterion, phase='train',
                                              points_ahead=points_ahead, encod_decode_model=self.encod_decode_model,
                                              device=self.device)  # , writer=writer)
            val_loss = self.model.run_epoch(val_iterator, None, criterion, phase='val', points_ahead=points_ahead,
                                            encod_decode_model=self.encod_decode_model,
                                            device=self.device)  # , writer=writer)

            history_train.append(train_loss)
            history_val.append(val_loss)

            if val_loss < best_val_loss:
                best_val_loss = val_loss
                torch.save(self.model.state_dict(), self.best_model_file)

            if show_figures:
                display.clear_output(wait=True)
                plt.figure()
                plt.plot(history_train, label='Train')
                plt.plot(history_val, label='Val')
                plt.xlabel('Epoch')
                plt.ylabel('MSE')
                plt.legend()
                plt.show()

            if show_progress:
                show_progress_text = f'Epoch: {epoch + 1:02} \n' + \
                                     f'\tTrain Loss: {train_loss:.3f} \n' + \
                                     f'\t Val. Loss: {val_loss:.3f} \n\n' +  \
                                     show_progress_text
                print(show_progress_text)




        self.model.load_state_dict(torch.load(self.best_model_file))

        if show_progress:
            print("After choosing the best model:")
            try:
                test_iterator = self.Loader(X_test, y_test, len(X_test), shuffle=False)
                test_loss = self.model.run_epoch(test_iterator, None, criterion, phase='val',
                                                 encod_decode_model=self.encod_decode_model, device=self.device)
                print(f'Test Loss: {test_loss:.3f}')
            except:
                print('Весь X_test не помещается в память, тестим усреднением по батчам')
                test_iterator = self.Loader(X_test, y_test, batch_size, shuffle=False)
                test_loss = []
                for epoch in range(n_epochs):
                    test_loss.append(self.model.run_epoch(test_iterator, None, criterion, phase='val',
                                                          encod_decode_model=self.encod_decode_model, device=self.device))
                print(f'Test Loss: {np.mean(test_loss):.3f}')


        # -----------------------------------------------------------------------------------------
        #     Генерация остатков
        # -----------------------------------------------------------------------------------------
        print('asdasdas',len(dfs))
        df_residuals = self._get_anomaly_timestamps(dfs=dfs)
        self.anomaly_timestamps = self.res_analys_alg.fit_predict(df_residuals, show_figure=show_figures)
        self.statistic = self.res_analys_alg.statistic
        self.ucl = self.res_analys_alg.ucl
        self.lcl = self.res_analys_alg.lcl

        at = pd.Series(self.anomaly_timestamps).to_frame()
        result = ResidualAnomalyDetectionResult()

        return at, result

    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++
    # xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
    # ++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++++

    # накосячил тут с прогнозом на одну точку вперед. Могут быть проблемы если ahead !=1
    def predict(self,
                        dfs,
                        result:ResidualAnomalyDetectionResult,
                        gap=0,
                        shag=1,
                        intersection=True,
                        train_size=None,
                        random_state=None,
                        shuffle=False,
                        stratify=None,
                        show_progress=True,
                        show_figures=True
                        ):

        """
        Поиск аномалий в новом наборе данных
        
        Parameters
        ----------
        см self.fit() dockstring
        
        
        Return
        ----------
        anomaly_timestamps : list of df.index.dtype
            Возвращает список временных меток аномалий                
        
        Attributes
        ----------
        
        """
        len_seq = self.len_seq
        # -----------------------------------------------------------------------------------------
        #     Генерация остатков
        # -----------------------------------------------------------------------------------------
        df_residuals = self._get_anomaly_timestamps(dfs=dfs)
        self.anomaly_timestamps = self.res_analys_alg.predict(df_residuals, show_figure=show_figures)
        self.statistic = self.res_analys_alg.statistic

        
        at = pd.Series(self.anomaly_timestamps).to_frame()
        result = ResidualAnomalyDetectionResult()

        return at, result

    def forecast(self, df, points_ahead=None, show_figures=True):
        """
        Прогнозирование временного ряда, в том числе векторного.
        
        Parameters
        ----------
        df : pd.core.series.Series or pd.core.frame.DataFrame data type
            Исходные данные. Данные не долнжны содержать np.nan вовсе, иметь постоянную 
            и одинковую частоту of df.index и при этом не иметь пропусков.         
                
        points_ahead : int, default=5
            Горизонт прогнозирования. 
               
        show_figures : bool, default=True
            Показывать или нет результаты решения задачии anomaly detection 
            и кривую трейна и валидации по эпохам. 
        
        
        Loader : class, default=iterators.Loader.
            Тип загрузчика, которую будет использовать как итератор в будущем, 
            благодаря которому, есть возможность бить на бачи.
        
                
        

        
        Attributes
        ----------
        
        """

        df = df.copy()
        points_ahead = points_ahead if points_ahead is not None else self.points_ahead
        len_seq = self.len_seq
        batch_size = self.batch_size

        assert (type(df) == pd.core.series.Series) | (type(df) == pd.core.frame.DataFrame)
        df = df.copy() if type(df) == pd.core.frame.DataFrame else pd.DataFrame(df)
        df = df[-len_seq:]
        assert not self._init_preproc
        preproc_values = self.preproc.transform(df)

        iterator = self.Loader(np.expand_dims(preproc_values, 0), np.expand_dims(preproc_values, 0),
                          # ничего страшного, 'y' все равно не используется
                          batch_size, shuffle=False)

        y_pred = self.model.run_epoch(iterator, None, None, phase='forecast', points_ahead=points_ahead, device=self.device)[
            0]
        y_pred = self.preproc.inverse_transform(y_pred)

        t_last = np.datetime64(df.index[-1])
        delta_dime = np.timedelta64(df.index[-1] - df.index[-2])
        new_index = pd.to_datetime(t_last + np.arange(1, points_ahead + 1) * delta_dime)
        y_pred = pd.DataFrame(y_pred, index=new_index, columns=df.columns)

        if show_figures:
            pd.concat([df, y_pred])[-3 * points_ahead:].plot()
            plt.axvspan(t_last, y_pred.index[-1], alpha=0.2, color='green', label='forecast')
            plt.xlabel('Datetime')
            plt.ylabel('Value')
            plt.legend()
            plt.show()

        return y_pred

    def save(self, path='./pipeline.pcl'):
        """
        Method for saving pipeline.
        It may be required for example after training.
        CPU.
        
        Parameters
        ----------
            path : str
        Путь до файла, для сохранения пайплайна. 
        Пайлайн сохраняется в формате pickle
        """

        self.model.run_epoch(self.Loader(torch.zeros((1, self.len_seq, self.model.in_features), dtype=float),
                                        torch.zeros((1, self.len_seq, self.model.in_features), dtype=float),
                                        batch_size=1),
                             None, None, phase='forecast', points_ahead=1, device=self.device)
        with open(path, 'wb') as f:
            pickle.dump(self, f)

    def load(self, path='./pipeline.pcl'):
        """
        Method for loading pipeline.
        It may be required for example after training.
        
        Parameters
        ----------
            path : str
        Путь до сохраненного файла пайплайна. 
        Пайлайн должен быть в формате pickle
        """
        with open(path, 'rb') as f:
            pipeline = pickle.load(f)
        self.__dict__.update(pipeline.__dict__)