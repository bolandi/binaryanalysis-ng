# Binary Analysis Next Generation (BANG!)
#
# This file is part of BANG.
#
# BANG is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License, version 3,
# as published by the Free Software Foundation.
#
# BANG is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public
# License, version 3, along with BANG.  If not, see
# <http://www.gnu.org/licenses/>
#
# Copyright Armijn Hemel
# Licensed under the terms of the GNU Affero General Public License
# version 3
# SPDX-License-Identifier: AGPL-3.0-only

import os
import pathlib

from bang.UnpackParser import UnpackParser, check_condition
from bang.UnpackParserException import UnpackParserException
from kaitaistruct import ValidationNotEqualError
from . import rkboot


class RockchipUnpackParser(UnpackParser):
    extensions = []
    signatures = [
        (0, b'BOOT')
    ]
    pretty_name = 'rkboot'

    def parse(self):
        self.unpacked_size = 0
        try:
            self.data = rkboot.Rkboot.from_io(self.infile)

            # ugly hack to read all the data
            for entry in self.data.entries_471:
                self.unpacked_size = max(self.unpacked_size, entry.ofs_data + entry.len_data)
            for entry in self.data.entries_472:
                self.unpacked_size = max(self.unpacked_size, entry.ofs_data + entry.len_data)
            for entry in self.data.entries_loader:
                self.unpacked_size = max(self.unpacked_size, entry.ofs_data + entry.len_data)
            # crc32 at the end of the file
            crc = self.data.crc
            self.unpacked_size += 4
        except (Exception, ValidationNotEqualError) as e:
            raise UnpackParserException(e.args)

    # make sure that self.unpacked_size is not overwritten
    def calculate_unpacked_size(self):
        pass

    labels = ['rockchip']
    metadata = {}

