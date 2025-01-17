from asynch.proto.io import BufferedReader, BufferedWriter


class BlockInfo:
    is_overflows = False
    bucket_num = -1

    def __init__(self, writer: BufferedWriter = None, reader: BufferedReader = None):
        self.writer = writer
        self.reader = reader

    async def write(self):
        # Set of pairs (`FIELD_NUM`, value) in binary form. Then 0.
        await self.writer.write_varint(1)
        await self.writer.write_uint8(self.is_overflows)
        await self.writer.write_varint(2)
        await self.writer.write_int32(self.bucket_num)
        await self.writer.write_varint(0)

    async def read(self):
        while True:
            field_num = await self.reader.read_varint()
            if not field_num:
                break

            if field_num == 1:
                self.is_overflows = bool(await self.reader.read_uint8())

            elif field_num == 2:
                self.bucket_num = await self.reader.read_uint32()


class BaseBlock:
    def __init__(
        self,
        writer: BufferedWriter = None,
        reader: BufferedReader = None,
        columns_with_types=None,
        data=None,
        info=None,
        types_check=False,
    ):
        self.writer = writer
        self.reader = reader
        self.columns_with_types = columns_with_types or []
        self.types_check = types_check
        self.info = info or BlockInfo(writer, reader)
        self.data = self.normalize(data or [])

    def normalize(self, data):
        return data

    @property
    def num_columns(self):
        raise NotImplementedError

    @property
    def num_rows(self):
        raise NotImplementedError

    def get_columns(self):
        raise NotImplementedError

    def get_rows(self):
        raise NotImplementedError

    def get_column_by_index(self, index):
        raise NotImplementedError

    def transposed(self):
        return list(zip(*self.data))


class ColumnOrientedBlock(BaseBlock):
    def normalize(self, data):
        if not data:
            return []

        self._check_number_of_columns(data)
        self._check_all_columns_equal_length(data)
        return data

    @property
    def num_columns(self):
        return len(self.data)

    @property
    def num_rows(self):
        return len(self.data[0]) if self.num_columns else 0

    def get_columns(self):
        return self.data

    def get_rows(self):
        return self.transposed()

    def get_column_by_index(self, index):
        return self.data[index]

    def _check_number_of_columns(self, data):
        expected_row_len = len(self.columns_with_types)

        got = len(data)
        if expected_row_len != got:
            msg = "Expected {} columns, got {}".format(expected_row_len, got)
            raise ValueError(msg)

    def _check_all_columns_equal_length(self, data):
        expected = len(data[0])

        for column in data:
            got = len(column)
            if got != expected:
                msg = "Expected {} rows, got {}".format(expected, got)
                raise ValueError(msg)


class RowOrientedBlock(BaseBlock):
    dict_row_types = (dict,)
    tuple_row_types = (list, tuple)
    supported_row_types = dict_row_types + tuple_row_types

    def normalize(self, data):
        if not data:
            return []

        # Guessing about whole data format by first row.
        first_row = data[0]

        if self.types_check:
            self._check_row_type(first_row)

        if isinstance(first_row, dict):
            self._mutate_dicts_to_rows(data)
        else:
            self._check_rows(data)

        return data

    @property
    def num_columns(self):
        return len(self.data[0]) if self.num_rows else 0

    @property
    def num_rows(self):
        return len(self.data)

    def get_columns(self):
        return self.transposed()

    def get_rows(self):
        return self.data

    def get_column_by_index(self, index):
        return [row[index] for row in self.data]

    def _mutate_dicts_to_rows(self, data):
        column_names = [x[0] for x in self.columns_with_types]

        check_row_type = False
        if self.types_check:
            check_row_type = self._check_dict_row_type

        for i, row in enumerate(data):
            if check_row_type:
                check_row_type(row)

            data[i] = [row[name] for name in column_names]

    def _check_rows(self, data):
        expected_row_len = len(self.columns_with_types)

        got = len(data[0])
        if expected_row_len != got:
            msg = "Expected {} columns, got {}".format(expected_row_len, got)
            raise ValueError(msg)

        if self.types_check:
            check_row_type = self._check_tuple_row_type
            for row in data:
                check_row_type(row)

    def _check_row_type(self, row):
        if not isinstance(row, self.supported_row_types):
            raise TypeError(
                "Unsupported row type: {}. dict, list or tuple is expected.".format(type(row))
            )

    def _check_tuple_row_type(self, row):
        if not isinstance(row, self.tuple_row_types):
            raise TypeError(
                "Unsupported row type: {}. list or tuple is expected.".format(type(row))
            )

    def _check_dict_row_type(self, row):
        if not isinstance(row, self.dict_row_types):
            raise TypeError("Unsupported row type: {}. dict is expected.".format(type(row)))


class BlockStreamProfileInfo:
    def __init__(self, reader: BufferedReader):
        self.rows = 0
        self.blocks = 0
        self.bytes = 0
        self.applied_limit = False  # bool
        self.rows_before_limit = 0
        self.calculated_rows_before_limit = 0  # bool
        self.reader = reader

    async def read(
        self,
    ):
        self.rows = await self.reader.read_varint()
        self.blocks = await self.reader.read_varint()
        self.bytes = await self.reader.read_varint()
        self.applied_limit = bool(await self.reader.read_uint8())
        self.rows_before_limit = await self.reader.read_varint()
        self.calculated_rows_before_limit = bool(await self.reader.read_uint8())
